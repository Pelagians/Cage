"""AppImage-only host integration; application lifecycle lives in desktop_launch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import shutil

from desktop_launch import (DesktopError, launch, digest_json, _write_state_record,
                            lifecycle_lock, _read_generations, _generation, _real_path, plan_identity, copy_file,
                            desktop_entry, snapshot_legacy, assert_quiescent, _flush_tree, validate_update_policy)


def refresh_desktop_cache(directory):
    tool = shutil.which('update-desktop-database')
    if tool:
        try:
            return subprocess.run([tool, str(directory)], check=False, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass  # Optional host cache maintenance cannot invalidate an installation.
    return False


def file_hash(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def desktop_quote(value):
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    # Desktop string escaping is applied before Exec's quoted-argument grammar.
    return '"' + value.replace('\\', '\\\\') + '"'


def integrate(root, plan, *, remove=False):
    """Explicit per-user integration; offer MIME handlers, retain user defaults/state."""
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))).resolve()
    app_id = plan['desktop']['id']
    directory = data / 'cage/appimages' / app_id
    package = directory / 'application.AppImage'
    receipt = directory / 'installation.json'
    desktop = data / 'applications' / (app_id + '.CageAppImage.desktop')
    icon = data / 'icons/hicolor/scalable/apps' / (app_id + '.CageAppImage.svg')
    if remove:
        if receipt.is_symlink() or not receipt.is_file():
            raise DesktopError('no Cage AppImage installation receipt; files retained')
        recorded = json.loads(receipt.read_text())
        expected = {'package': package, 'desktop': desktop, 'icon': icon}
        for name, path in expected.items():
            if path.is_symlink() or not path.is_file() or file_hash(path) != recorded.get(name):
                raise DesktopError('installed files changed; retain them for manual recovery')
        retained = []
        for entry in recorded.get('versions', []):
            path = _real_path(directory, entry['package'])
            if not path.is_file() or file_hash(path) != entry['sha256']:
                raise DesktopError('retained AppImage changed; files retained')
            retained.append(path)
        versions = _real_path(directory, 'versions')
        if versions.exists() and set(versions.iterdir()) != set(retained):
            raise DesktopError('untracked update files retained; recover them before uninstalling')
        allowed = {'application.AppImage', 'installation.json', 'versions', 'launch.lock'}
        if {path.name for path in directory.iterdir()} - allowed:
            raise DesktopError('untracked installation files retained; recover them before uninstalling')
        for path in retained:
            path.unlink()
        if (directory / 'versions').exists():
            (directory / 'versions').rmdir()
        for path in expected.values():
            path.unlink()
        (directory / 'launch.lock').unlink(missing_ok=True)
        receipt.unlink()
        directory.rmdir()
        refresh_desktop_cache(desktop.parent)
        return {'removed': True, 'userStateRetained': True}
    source = Path(os.environ.get('APPIMAGE', ''))
    if not source.is_file():
        raise DesktopError('desktop installation requires the original .AppImage, not an extracted AppDir')
    with source.open('rb') as handle:
        if handle.read(4) != b'\x7fELF':
            raise DesktopError('desktop installation requires the original .AppImage')
    if any(path.exists() or path.is_symlink() for path in (directory, desktop, icon)):
        raise DesktopError('AppImage desktop installation already exists; upgrades are not implemented')
    directory.mkdir(parents=True, mode=0o700)
    try:
        copy_file(source, package)
        package.chmod(0o755)
        desktop.parent.mkdir(parents=True, exist_ok=True)
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_bytes((root / (app_id + '.svg')).read_bytes())
        desktop.write_text(desktop_entry(plan,
            # GIO checks argv[0] before expanding %% in a desktop Exec value.
            # env keeps literal percent characters in an ordinary argument.
            '/usr/bin/env ' + desktop_quote(package) + ' -- %F',
            icon=app_id + '.CageAppImage', suffix=' (AppImage)'))
        recorded = {name: file_hash(path) for name, path in
                    {'package': package, 'desktop': desktop, 'icon': icon}.items()}
        recorded.update(schemaVersion='cage.appimage-installation/v1', versions=[])
        _write_state_record(receipt, recorded)
        refresh_desktop_cache(desktop.parent)
    except BaseException:
        # All paths were absent before this explicit installation.
        for path in (desktop, icon, package, receipt):
            path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return {'installed': str(package), 'desktop': str(desktop), 'userStateRetained': True}


def package_identity(plan):
    return plan_identity(plan)


def installed_directory(plan):
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))).resolve()
    return data / 'cage/appimages' / plan['desktop']['id']


def stage_update(plan):
    """Retain exact package bytes before any state transition; never fetch code."""
    directory = installed_directory(plan)
    if not (directory / 'installation.json').is_file():
        return  # Direct, unintegrated packages use their original artifact paths.
    with lifecycle_lock(directory):
        package = directory / 'application.AppImage'
        receipt = directory / 'installation.json'
        recorded = json.loads(receipt.read_text())
        if package.is_symlink() or file_hash(package) != recorded['package']:
            raise DesktopError('installed AppImage changed; retain it for recovery')
        if recorded.get('schemaVersion') != 'cage.appimage-installation/v1':
            raise DesktopError('reinstall a generation-aware baseline before updating this integration')
        source = Path(os.environ.get('APPIMAGE', ''))
        if not source.is_file() or source.is_symlink():
            raise DesktopError('updating integration requires the original AppImage')
        digest = file_hash(source)
        if digest == recorded['package']:
            return  # The stable baseline is already retained byte for byte.
        matches = [e for e in recorded.get('versions', []) if e['identity'] == package_identity(plan)]
        if matches:
            path = _real_path(directory, matches[0]['package'])
            if not path.is_file() or file_hash(path) != matches[0]['sha256']:
                raise DesktopError('retained AppImage candidate changed')
            return  # Equivalent contract already has retained exact bytes.
        versions = directory / 'versions'
        if versions.is_symlink():
            raise DesktopError('linked AppImage versions directory')
        versions.mkdir(mode=0o700, exist_ok=True)
        destination = versions / (digest + '.AppImage')
        if destination.is_symlink():
            raise DesktopError('linked AppImage candidate')
        if not destination.exists():
            temporary = versions / (digest + '.partial')
            if temporary.exists() or temporary.is_symlink():
                raise DesktopError('interrupted package copy retained; move it aside before retrying')
            copy_file(source, temporary)
            with temporary.open('rb') as dst:
                os.fsync(dst.fileno())
            temporary.chmod(0o755)
            if file_hash(temporary) != digest:
                raise DesktopError('candidate changed while copying')
            temporary.replace(destination)
        elif file_hash(destination) != digest:
            raise DesktopError('retained AppImage candidate changed')
        entries = recorded.setdefault('versions', [])
        entry = {'package': 'versions/' + destination.name, 'sha256': digest,
                 'identity': package_identity(plan)}
        if not any(e['identity'] == entry['identity'] for e in entries):
            entries.append(entry)
        _write_state_record(receipt, recorded)


def dispatch_installed(plan, arguments):
    """The stable menu artifact resolves the package matching the active state.

    A single atomic state pointer chooses both prefix and previously staged
    package. There is no unsafe package/state two-file replacement window.
    """
    directory = installed_directory(plan)
    source = Path(os.environ.get('APPIMAGE', '')).absolute()
    if source != directory / 'application.AppImage':
        return
    receipt = directory / 'installation.json'
    if receipt.is_symlink() or not receipt.is_file():
        raise DesktopError('missing installation receipt')
    recorded = json.loads(receipt.read_text())
    if file_hash(source) != recorded['package']:
        raise DesktopError('installed AppImage changed')
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    state = data / 'cage/appimage' / plan['desktop']['id']
    with lifecycle_lock(state):
        generations = _read_generations(state)
        if not generations:
            return
        active = _generation(generations, generations['active'])['identity']
        if active == package_identity(plan):
            return
        entries = [e for e in recorded.get('versions', []) if e['identity'] == active]
        if len(entries) != 1:
            raise DesktopError('active state package unavailable; retain state and restore its artifact')
        entry = entries[0]
        package = _real_path(directory, entry['package'])
        if not package.is_file() or file_hash(package) != entry['sha256']:
            raise DesktopError('retained AppImage changed; rollback package not trusted')
    os.execv(str(package), [str(package), *arguments])


def migration_state(plan):
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    return data / 'cage/appimage' / plan['desktop']['id']


def recover_migration(root, plan):
    """Recover integration from committed state; never restore over a prefix."""
    state = migration_state(plan)
    with lifecycle_lock(state):
        journal = json.loads(_real_path(state, 'appimage-migration.json').read_text())
        if journal['targetIdentity'] != plan_identity(plan):
            raise DesktopError('migration recovery requires its exact managed baseline')
        backup = _real_path(state, journal['snapshot'])
        package = _real_path(backup, 'baseline.AppImage')
        if file_hash(package) != journal['baselineSha256']:
            raise DesktopError('retained migration baseline changed; all files retained')
        record = _read_generations(state)
        active = _generation(record, record['active'])['identity']
        if active not in (journal['identity'], journal['targetIdentity']):
            raise DesktopError('state belongs to a later generation; migration recovery refused')
        if active == journal['identity'] and journal['hadIntegration']:
            saved = _real_path(backup, 'integration')
            installed = json.loads(_real_path(saved, 'installation.json').read_text())
            for name, path in {'package': _real_path(saved, 'application.AppImage'),
                               'desktop': _real_path(backup, 'desktop'), 'icon': _real_path(backup, 'icon')}.items():
                if file_hash(path) != installed[name]:
                    raise DesktopError('retained legacy integration changed; recovery refused without moving files')
            if installed['package'] != journal['previousSha256']:
                raise DesktopError('retained legacy package differs from migration receipt')
        directory = installed_directory(plan)
        data = directory.parents[2]
        desktop = data / 'applications' / (plan['desktop']['id'] + '.CageAppImage.desktop')
        icon = data / 'icons/hicolor/scalable/apps' / (plan['desktop']['id'] + '.CageAppImage.svg')
        # Preserve partial or changed integration in full before restoring the
        # selected one. This namespace never contains application prefixes.
        import uuid
        retained = backup / ('integration-recovery-' + uuid.uuid4().hex)
        retained.mkdir(mode=0o700)
        for name, path in {'installation': directory, 'desktop': desktop, 'icon': icon}.items():
            if path.is_symlink():
                raise DesktopError('linked integration path; all files retained')
            if path.exists():
                path.rename(retained / name)
        if active == journal['identity']:
            if journal['hadIntegration']:
                saved = _real_path(backup, 'integration')
                directory.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(saved, directory, copy_function=copy_file)
                for name, path in {'desktop': desktop, 'icon': icon}.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    copy_file(backup / name, path)
        else:
            original = os.environ.get('APPIMAGE')
            try:
                os.environ['APPIMAGE'] = str(package)
                integrate(root, plan)
            finally:
                if original is None:
                    os.environ.pop('APPIMAGE', None)
                else:
                    os.environ['APPIMAGE'] = original
        refresh_desktop_cache(desktop.parent)
        journal.update(status='recovered', selected='legacy' if active == journal['identity'] else 'managed')
        _write_state_record(state / 'appimage-migration.json', journal)
        return {'recovered': True, 'integration': journal['selected'], 'legacySnapshot': str(backup), 'stateRetained': True}


def migrate(root, metadata, plan, previous, files):
    validate_update_policy(plan.get('desktop', {}).get('updates'))
    previous = Path(previous).absolute()
    receipt = Path(str(previous) + '.json')
    if previous.is_symlink() or receipt.is_symlink():
        raise DesktopError('retain the exact legacy AppImage and adjacent export receipt')
    exported = json.loads(receipt.read_text())
    old = exported['plan']
    if (exported.get('schemaVersion') != 'cage.appimage-export-result/v0'
            or file_hash(previous) != exported.get('sha256') or old.get('format') != 'appimage'
            or old.get('application') != plan.get('application') or old.get('desktop', {}).get('id') != plan['desktop']['id']
            or old.get('target') != plan.get('target') or old.get('state', {}).get('managerVersion') is not None):
        raise DesktopError('migration requires the exact legacy package and same-version/runtime baseline')
    state = migration_state(plan)
    with lifecycle_lock(state):
        pending = _real_path(state, 'appimage-migration.json')
        if pending.exists() and json.loads(pending.read_text()).get('status') == 'prepared':
            raise DesktopError('unfinished migration; use --cage-recover-migration first')
        record = _read_generations(state)
        if not record or _generation(record, record['active'])['identity'] != plan_identity(old):
            raise DesktopError('legacy package and recorded state differ; all files retained')
        usr = Path(metadata).parents[3]
        environment = {**os.environ, 'LD_LIBRARY_PATH': str(usr / 'lib/cage-native')}
        assert_quiescent(state, str(usr / 'wine' / plan['target']['wineserver']), environment)
        backup = snapshot_legacy(state, plan_identity(plan), reuse=False)
        directory = installed_directory(plan)
        data = directory.parents[2]
        desktop = data / 'applications' / (plan['desktop']['id'] + '.CageAppImage.desktop')
        icon = data / 'icons/hicolor/scalable/apps' / (plan['desktop']['id'] + '.CageAppImage.svg')
        had = directory.exists()
        if had:
            if directory.is_symlink() or any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
                raise DesktopError('linked or untracked legacy installation files; all files retained')
            if {p.name for p in directory.iterdir()} - {'application.AppImage', 'installation.json', 'launch.lock'}:
                raise DesktopError('untracked legacy installation files; all files retained')
            installed = json.loads((directory / 'installation.json').read_text())
            if installed.get('schemaVersion') == 'cage.appimage-installation/v1' or installed['package'] != exported['sha256']:
                raise DesktopError('integration does not match the legacy AppImage')
            for name, path in {'package': directory / 'application.AppImage', 'desktop': desktop, 'icon': icon}.items():
                if path.is_symlink() or file_hash(path) != installed[name]:
                    raise DesktopError('legacy integration changed; all files retained')
            shutil.copytree(directory, backup / 'integration', copy_function=copy_file)
            copy_file(desktop, backup / 'desktop')
            copy_file(icon, backup / 'icon')
        elif any(p.exists() or p.is_symlink() for p in (desktop, icon)):
            raise DesktopError('untracked desktop integration retained; migration refused')
        copy_file(previous, backup / 'previous.AppImage')
        copy_file(receipt, backup / 'previous.AppImage.json')
        source = Path(os.environ['APPIMAGE'])
        copy_file(source, backup / 'baseline.AppImage')
        _flush_tree(backup)
        journal = {'schemaVersion': 'cage.appimage-migration/v1', 'status': 'prepared',
                   'snapshot': str(backup.relative_to(state)), 'identity': plan_identity(old),
                   'targetIdentity': plan_identity(plan), 'hadIntegration': had,
                   'previousSha256': exported['sha256'], 'baselineSha256': file_hash(source)}
        _write_state_record(pending, journal)
    try:
        with lifecycle_lock(state):
            if had:
                integrate(root, plan, remove=True)
            integrate(root, plan)
        result = launch(metadata, ['--cage-migrate', '--', *files])
        if result:
            recover_migration(root, plan)
            return result
    except BaseException:
        recover_migration(root, plan)
        raise
    journal.update(status='committed')
    _write_state_record(pending, journal)
    print(json.dumps({'migrated': True, 'legacySnapshot': str(backup), 'stateRetained': True,
                      'nextStep': 'use the normal managed update from this baseline'}))
    return 0


def main(root, arguments):
    root = Path(root).resolve()
    plans = list((root / 'usr/share/cage').glob('*/desktop.json'))
    if len(plans) != 1:
        raise DesktopError('missing or ambiguous application metadata')
    metadata = plans[0]
    plan = json.loads(metadata.read_text())
    if platform.machine() != plan['target']['architecture']:
        raise DesktopError('this AppImage was built for ' + plan['target']['architecture'])
    if arguments == ['--cage-info']:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if arguments == ['--cage-recover-migration']:
        print(json.dumps(recover_migration(root, plan), indent=2))
        return 0
    if arguments[:1] == ['--cage-migrate']:
        if len(arguments) < 3 or arguments[1] != '--previous-package' or (len(arguments) > 3 and arguments[3] != '--'):
            raise DesktopError('--cage-migrate requires --previous-package OLD.AppImage [-- files...]')
        return migrate(root, metadata, plan, arguments[2], arguments[4:])
    journal = migration_state(plan) / 'appimage-migration.json'
    if journal.exists() and arguments not in (['--cage-state-info'], ['--cage-display-info']):
        if journal.is_symlink() or json.loads(journal.read_text()).get('status') == 'prepared':
            raise DesktopError('unfinished migration; use --cage-recover-migration first')
    if arguments in (['--cage-install'], ['--cage-uninstall']):
        data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
        with lifecycle_lock(data / 'cage/appimage' / plan['desktop']['id']):
            print(json.dumps(integrate(root, plan, remove=arguments == ['--cage-uninstall']), indent=2))
        return 0
    if arguments[:1] in (['--cage-update'], ['--cage-rollback']):
        data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
        with lifecycle_lock(data / 'cage/appimage' / plan['desktop']['id']):
            stage_update(plan)
        return launch(metadata, arguments)
    if arguments in (['--cage-state-info'], ['--cage-display-info']) or arguments[:1] == ['--cage-dpi']:
        return launch(metadata, arguments)
    dispatch_installed(plan, arguments)
    if arguments[:1] == ['--']:
        arguments = arguments[1:]
    elif arguments and arguments[0].startswith('--cage-'):
        raise DesktopError('unknown Cage AppImage option')
    return launch(metadata, arguments)


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1], sys.argv[2:]))
    except (DesktopError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Cage AppImage: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
