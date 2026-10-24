"""Local Flatpak package transactions paired with Cage's prefix generations.

No remote updater or new service: retain user-supplied Cage exports, use Flatpak
for deployment, and recover deployment from the authoritative prefix identity.
Hashes bind local receipts to bytes; they are not publisher authentication.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess

from core.manifest.desktop import normalize_desktop
from core.manifest.errors import ManifestError

from runtime.desktop_launch import (DesktopError, copy_file, lifecycle_lock,
                                   _write_state_record, _real_path, plan_identity,
                                   _read_generations, _generation, snapshot_legacy, migration_space,
                                   validate_runtime_update, rollback_repair_source)


def identity(plan):
    return plan_identity(plan)


def checked_export(package, *, allow_legacy=False):
    package = Path(package).absolute()
    receipt = Path(str(package) + '.json')
    if package.is_symlink() or receipt.is_symlink() or not package.is_file() or not receipt.is_file():
        raise DesktopError('retain both the original Cage Flatpak bundle and its .json export receipt')
    result = json.loads(receipt.read_text())
    with package.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    plan = result.get('plan', {})
    if (not isinstance(plan, dict) or result.get('schemaVersion') != 'cage.flatpak-export-result/v0' or result.get('sha256') != digest
            or plan.get('format') != 'flatpak'
            or (plan.get('state', {}).get('managerVersion') != 1 and
                (not allow_legacy or plan.get('state', {}).get('managerVersion') is not None))):
        raise DesktopError('bundle/receipt mismatch or pre-generation export; re-export a baseline with the current Cage first')
    try:
        normalize_desktop(plan.get('desktop'))
        if plan.get('target', {}).get('architecture') not in {'x86_64', 'aarch64'} or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', plan.get('branch', '')):
            raise ValueError('invalid architecture/branch')
    except (ManifestError, TypeError, ValueError) as exc:
        raise DesktopError('invalid Flatpak export identity/policy; no deployment changed') from exc
    if not allow_legacy and not plan.get('desktop', {}).get('updates'):
        raise DesktopError('Flatpak update requires a qualified recipe migration policy')
    return {'sha256': digest, 'identity': identity(plan), 'plan': plan}, package


def _command(arguments, environment, *, capture=True):
    result = subprocess.run(['flatpak', *arguments], env=environment, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        raise DesktopError('flatpak ' + arguments[0] + ' failed: ' + (result.stderr or 'see application output'))
    return result.stdout.strip() if capture else ''


def _ref(entry):
    plan = entry['plan']
    return plan['desktop']['id'] + '/' + plan['target']['architecture'] + '/' + plan['branch']


def _state(entry, environment):
    return json.loads(_command(['run', '--user', _ref(entry), '--cage-state-info'], environment))


def _active(info):
    record = info.get('state')
    if not record:
        return None
    entries = [g for g in record['generations'] if g['prefix'] == record['active']]
    if len(entries) != 1:
        raise DesktopError('ambiguous Flatpak state identity; retain all bundles and state')
    return entries[0]['identity']


def _install(directory, entry, environment):
    package = _real_path(directory, entry['sha256'] + '.flatpak')
    with package.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != entry['sha256']:
            raise DesktopError('retained Flatpak bundle changed; deployment refused')
    # A repeated repair or recovery can select the already deployed commit.
    # Flatpak otherwise refuses it before Cage can run the state transaction.
    _command(['install', '--user', '--noninteractive', '--assumeyes', '--reinstall', '--no-related', '--no-deps',
              '--bundle', str(package)], environment)


def _retain(directory, entry, source):
    destination = _real_path(directory, entry['sha256'] + '.flatpak')
    if not destination.exists():
        temporary = directory / (entry['sha256'] + '.partial')
        if temporary.exists() or temporary.is_symlink():
            raise DesktopError('interrupted package copy retained; move it aside before retrying')
        copy_file(source, temporary)
        with temporary.open('rb') as handle:
            os.fsync(handle.fileno())
        temporary.replace(destination)
    with destination.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != entry['sha256']:
            raise DesktopError('retained package changed; no deployment changed')
    _write_state_record(Path(str(destination) + '.json'), {'schemaVersion': 'cage.flatpak-export-result/v0',
                        'sha256': entry['sha256'], 'plan': entry['plan']})


def recover_flatpak(directory, *, environment=None):
    directory = Path(directory)
    environment = dict(os.environ if environment is None else environment)
    with lifecycle_lock(directory):
        return _recover(directory, environment)


def _recover(directory, environment):
    journal = json.loads(_real_path(directory, 'transaction.json').read_text())
    if journal.get('schemaVersion') == 'cage.flatpak-migration/v1':
        root = Path(journal['stateDirectory'])
        with lifecycle_lock(root):
            active = _generation(_read_generations(root), _read_generations(root)['active'])['identity']
            matches = [e for e in (journal['candidate'], journal['previous']) if e['identity'] == active]
            if len(matches) != 1:
                raise DesktopError('migration state does not match retained packages; all state retained')
            selected = matches[0]
            _install(directory, selected, environment)
            journal.update(status='recovered', deployed=selected['sha256'])
            _write_state_record(directory / 'transaction.json', journal)
            return {'recovered': True, 'packageSha256': selected['sha256'], 'stateRetained': True,
                    'legacySnapshot': journal['snapshot']}
    # Both baseline and candidate have the same ref and generation-aware helper.
    active = _active(_state(journal['candidate'], environment))
    matches = [e for e in (journal['candidate'], journal['previous']) if e['identity'] == active]
    if active is None:
        selected = journal['previous']
    elif not matches:
        raise DesktopError('state does not match either retained package; no deployment changed')
    else:
        selected = matches[0]
    _install(directory, selected, environment)
    journal.update(status='recovered', deployed=selected['sha256'])
    _write_state_record(directory / 'transaction.json', journal)
    return {'recovered': True, 'packageSha256': selected['sha256'], 'stateRetained': True}


def migrate_flatpak(package, previous_package, *, files=(), cache=None, state_dir=None, environment=None):
    """Adopt a same-version managed baseline; never relabel an untracked prefix."""
    candidate, source = checked_export(package)
    previous, old_source = checked_export(previous_package, allow_legacy=True)
    application = previous['plan'].get('application')
    if (not isinstance(application, dict) or not application.get('name') or not application.get('version')
            or _ref(candidate) != _ref(previous) or candidate['plan'].get('application') != application
            or previous['identity'].get('schemaVersion') != 'cage.desktop-state/v0'
            or candidate['identity']['runtimeDigest'] != previous['identity']['runtimeDigest']):
        raise DesktopError('migration requires the exact legacy package and same-version/runtime baseline')
    environment = dict(os.environ if environment is None else environment)
    app = candidate['plan']['desktop']['id']
    root = Path(state_dir) if state_dir else Path.home() / '.var/app' / app / 'data' / app
    directory = Path(cache) if cache else Path(environment.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'cage/package-updates/flatpak' / app
    with lifecycle_lock(directory):
        journal_path = _real_path(directory, 'transaction.json')
        if journal_path.exists() and json.loads(journal_path.read_text()).get('status') == 'prepared':
            raise DesktopError('unfinished package transaction; run cage recover-flatpak first')
        if app in _command(['ps', '--columns=application'], environment).splitlines():
            raise DesktopError('close the installed application before migration')
        # A short-lived metadata probe can remain in `flatpak ps` briefly
        # after its command exits. Check real running instances before it.
        installed = json.loads(_command(['run', '--user', '--command=cat', _ref(candidate),
                                        '/app/share/cage/' + app + '/desktop.json'], environment))
        if installed != previous['plan']:
            raise DesktopError('installed package does not match the supplied legacy export; no deployment changed')
        with lifecycle_lock(root):
            record = _read_generations(root)
            if not record or _generation(record, record['active'])['identity'] != previous['identity']:
                raise DesktopError('legacy package and recorded state differ; all state retained')
            # Both artifacts and an independently verified prefix snapshot exist
            # before the first deployment change. The original prefix stays put.
            _retain(directory, previous, old_source)
            _retain(directory, candidate, source)
            snapshot = snapshot_legacy(root, candidate['identity'])
        journal = {'schemaVersion': 'cage.flatpak-migration/v1', 'status': 'prepared',
                   'candidate': candidate, 'previous': previous, 'stateDirectory': str(root.absolute()),
                   'snapshot': str(snapshot), 'action': 'migrate'}
        _write_state_record(journal_path, journal)
        try:
            _install(directory, candidate, environment)
            info = _state(candidate, environment)
            if (info.get('stateDirectory') != str(root.absolute()) or _active(info) != previous['identity']):
                raise DesktopError('deployed application resolves a different state directory; trial refused')
            _command(['run', '--user', _ref(candidate), '--cage-migrate', '--', *map(str, files)], environment, capture=False)
            if _active(_state(candidate, environment)) != candidate['identity']:
                raise DesktopError('migration trial did not activate the baseline')
        except BaseException:
            _recover(directory, environment)
            raise
        journal.update(status='committed', deployed=candidate['sha256'])
        _write_state_record(journal_path, journal)
        return {'migrated': True, 'ref': _ref(candidate), 'recoveryDirectory': str(directory),
                'legacySnapshot': str(snapshot), 'stateRetained': True,
                'nextStep': 'update from this managed baseline with the normal update command'}


def update_flatpak(package, previous_package, *, rollback=False, repair=False, files=(), cache=None, environment=None):
    if rollback and repair:
        raise DesktopError('choose exact rollback or repaired rollback explicitly')
    candidate, source = checked_export(package)
    previous, old_source = checked_export(previous_package)
    if _ref(candidate) != _ref(previous):
        raise DesktopError('update and previous bundle must have the same application ID, architecture and branch')
    if candidate['plan']['desktop']['updates'].get('profile') != previous['plan']['desktop']['updates'].get('profile'):
        raise DesktopError('incompatible migration profiles; no deployment changed')
    if not rollback and not repair:
        validate_runtime_update(previous['plan'], candidate['plan'])
    if candidate['identity'] == previous['identity'] and not repair:
        raise DesktopError('package update has no new application/runtime generation')
    environment = dict(os.environ if environment is None else environment)
    directory = Path(cache) if cache else Path(environment.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'cage/package-updates/flatpak' / candidate['plan']['desktop']['id']
    with lifecycle_lock(directory):
        journal_path = _real_path(directory, "transaction.json")
        if journal_path.exists() and json.loads(journal_path.read_text()).get("status") == "prepared":
            raise DesktopError("unfinished package transaction; run cage recover-flatpak on this cache first")
        ref = _ref(candidate)
        metadata_path = '/app/share/cage/' + candidate['plan']['desktop']['id'] + '/desktop.json'
        installed_plan = json.loads(_command(['run', '--user', '--command=cat', ref, metadata_path], environment))
        if identity(installed_plan) != previous['identity']:
            raise DesktopError('installed package does not match --previous-package; no deployment changed')
        state = _state(previous, environment)
        active = _active(state)
        if active is None:
            raise DesktopError('launch the installed baseline once before updating; no deployment changed')
        if active != previous['identity']:
            raise DesktopError('installed package and active state differ; run cage recover-flatpak first')
        if repair:
            source_generation, _ = rollback_repair_source(state['state'], candidate['identity'], candidate['plan'])
            if source_generation['identity'] == previous['identity']:
                validate_runtime_update(previous['plan'], candidate['plan'], repair=True)
        # Retain both exact artifacts before deployment changes or user-code runs.
        _retain(directory, previous, old_source)
        _retain(directory, candidate, source)
        journal = {'schemaVersion': 'cage.flatpak-update/v1', 'status': 'prepared',
                   'candidate': candidate, 'previous': previous,
                   'action': 'rollback-repair' if repair else 'rollback' if rollback else 'update'}
        _write_state_record(directory / 'transaction.json', journal)
        try:
            _install(directory, candidate, environment)
            _command(['run', '--user', ref, '--cage-' + journal['action'], '--', *map(str, files)],
                     environment, capture=False)
            if _active(_state(candidate, environment)) != candidate['identity']:
                raise DesktopError('trial did not activate the requested generation')
        except BaseException:
            # If interrupted, the same operation is available explicitly on the
            # next run. Never guess from an exit code after a durable commit.
            _recover(directory, environment)
            raise
        journal.update(status='committed', deployed=candidate['sha256'])
        _write_state_record(directory / 'transaction.json', journal)
        return {'updated': not rollback and not repair, 'rolledBack': rollback, 'repairedRollback': repair, 'ref': ref,
                'recoveryDirectory': str(directory), 'stateRetained': True}
