"""AppImage-only host integration; application lifecycle lives in desktop_launch."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from desktop_launch import (DesktopError, launch, digest_json, _write_state_record,
                            lifecycle_lock, _read_generations, _generation, _real_path, plan_identity, copy_file)


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
    """Explicit per-user integration; never register associations or erase state."""
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
        for path in retained:
            path.unlink()
        if (directory / 'versions').exists():
            (directory / 'versions').rmdir()
        for path in expected.values():
            path.unlink()
        (directory / 'launch.lock').unlink(missing_ok=True)
        receipt.unlink()
        directory.rmdir()
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
        metadata = plan['desktop']
        desktop.write_text('[Desktop Entry]\nType=Application\n'
            + 'Name=' + metadata['name'].replace('\\', '\\\\') + ' (AppImage)\n'
            + 'Comment=' + metadata['summary'].replace('\\', '\\\\') + '\n'
            # GIO checks argv[0] before expanding %% in a desktop Exec value.
            # env keeps literal percent characters in an ordinary argument.
            + 'Exec=/usr/bin/env ' + desktop_quote(package) + ' -- %F\n'
            + 'Icon=' + app_id + '.CageAppImage\n'
            + 'Categories=' + ';'.join(metadata['categories']) + ';\nTerminal=false\n')
        recorded = {name: file_hash(path) for name, path in
                    {'package': package, 'desktop': desktop, 'icon': icon}.items()}
        recorded.update(schemaVersion='cage.appimage-installation/v1', versions=[])
        _write_state_record(receipt, recorded)
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
    if arguments == ['--cage-state-info']:
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
