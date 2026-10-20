"""Read-only storage diagnostics and conservative cleanup of build-only files.

There is no state database: existing artifact indices, package receipts and
prefix-generation records remain authoritative. Only completed export producers
can mark staging disposable. Prefixes and rollback artifacts are never pruned.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

from artifact.index import ARTIFACT_INDEX_SCHEMA_VERSION, ArtifactIndexError, empty_index
from runtime.desktop_launch import DesktopError, state_info

MARKER = '.cage-storage.json'
SCHEMA = 'cage.build-storage/v1'
DISPOSABLE = {'appimage': {'AppDir', 'payload.squashfs'},
              'flatpak': {'app', 'repository'}, 'oci': {'bundle', 'lifecycle', 'linux-state.tar'}}
STATE_FILES = {'state.json', '.cage-state.json', 'transaction.json', 'installation.json', 'launch.lock'}


class StorageError(RuntimeError):
    pass


def real_path(value):
    """Reject links in every component, including a supplied directory's parents."""
    path = Path(os.path.abspath(value))
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise StorageError('linked storage path retained: ' + str(part))
    return path


@contextmanager
def directory_fd(path):
    path = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def lock_path(path):
    path = real_path(path)
    return path.with_name(path.name + '.cage-build.lock')


@contextmanager
def build_lock(path, *, create=True):
    """Stable adjacent lock: neither context pruning nor cache pruning unlinks it."""
    lock = lock_path(path)
    if create:
        lock.parent.mkdir(parents=True, exist_ok=True)
    with directory_fd(lock.parent) as parent:
        fd = os.open(lock.name, os.O_NONBLOCK | os.O_NOFOLLOW | (os.O_CREAT | os.O_RDWR if create else os.O_RDONLY), 0o600, dir_fd=parent)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise StorageError('storage lock is not a regular file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StorageError('build/cache is busy; nothing removed: ' + str(path)) from exc
        yield
    finally:
        os.close(fd)


def read_json(path):
    path = real_path(path)
    with directory_fd(path.parent) as parent:
        file = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(file) as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise StorageError('metadata is not a regular file: ' + str(path))
        value = json.load(handle)
    if not isinstance(value, dict):
        raise StorageError('JSON object required: ' + str(path))
    return value


def _token(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns]


def _entry(fd, name, *, sync=False):
    before = os.stat(name, dir_fd=fd, follow_symlinks=False)
    value = {'stat': _token(before)}
    if stat.S_ISREG(before.st_mode):
        file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file, 'rb') as handle:
            if _token(os.fstat(handle.fileno())) != value['stat']:
                raise StorageError('file changed during inspection')
            value['sha256'] = hashlib.file_digest(handle, 'sha256').hexdigest()
            if _token(os.fstat(handle.fileno())) != value['stat']:
                raise StorageError('file changed during inspection')
            if sync:
                os.fsync(handle.fileno())
    elif stat.S_ISLNK(before.st_mode):
        value['link'] = os.readlink(name, dir_fd=fd)
    elif not stat.S_ISDIR(before.st_mode):
        raise StorageError('special file retained: ' + name)
    if _token(os.stat(name, dir_fd=fd, follow_symlinks=False)) != value['stat']:
        raise StorageError('path changed during inspection')
    return value


def snapshot(path):
    """No followed links, crossed mounts, special files, or mutable state markers."""
    result = {}
    with directory_fd(path) as root:
        device = os.fstat(root).st_dev
        for folder, dirs, files, fd in os.fwalk('.', dir_fd=root, follow_symlinks=False):
            for name in sorted(dirs + files):
                relative = (Path(folder) / name).as_posix()
                if relative == MARKER:
                    continue
                if name in STATE_FILES:
                    raise StorageError('application/recovery state found; entire context retained: ' + relative)
                entry = _entry(fd, name)
                if entry['stat'][0] != device:
                    raise StorageError('mounted storage retained: ' + relative)
                result[relative] = entry
    return result


def _write_marker(path, value):
    with directory_fd(path) as fd:
        temporary = '.storage-' + uuid.uuid4().hex
        try:
            file = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(file, 'w') as handle:
                json.dump(value, handle, sort_keys=True)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, MARKER, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass


def complete_export(context, bundle, kind, artifact):
    """Called by a successful exporter while its build lock is held."""
    context, bundle = real_path(context), real_path(bundle)
    if context.is_relative_to(bundle) or bundle.is_relative_to(context):
        raise StorageError('source bundle overlaps staging; cleanup registration refused')
    if any(context.is_relative_to(real_path(path)) for path in protected_roots()):
        raise StorageError('application installation/state namespace cannot be disposable staging')
    if kind not in DISPOSABLE:
        raise StorageError('unknown export format')
    if artifact.get('kind') != ('oci' if kind == 'oci' else 'file'):
        raise StorageError('export artifact kind does not match its staging format')
    _verify_artifact(artifact, context, sync=True)
    record = {'schemaVersion': SCHEMA, 'status': 'complete', 'kind': kind,
              'context': str(context), 'sourceBundle': str(bundle), 'artifact': artifact,
              'completedAt': time.time(), 'entries': snapshot(context)}
    _write_marker(context, record)
    return {'managed': True, 'marker': str(context / MARKER)}


def record_export(context, bundle, kind, artifact):
    # Cleanup bookkeeping must never invalidate an otherwise successful export.
    try:
        return complete_export(context, bundle, kind, artifact)
    except (OSError, ValueError, TypeError, KeyError, StorageError, subprocess.SubprocessError) as exc:
        return {'managed': False, 'reason': str(exc), 'stagingRetained': True}


def _verify_artifact(artifact, context, *, sync=False):
    if artifact['kind'] == 'file':
        path = real_path(artifact['path'])
        if path.is_relative_to(context):
            raise StorageError('exported package is inside staging; retain everything')
        with directory_fd(path.parent) as fd:
            entry = _entry(fd, path.name, sync=sync)
            if sync:
                os.fsync(fd)
        if entry.get('sha256') != artifact['sha256']:
            raise StorageError('retained package missing or changed; staging retained')
    elif artifact['kind'] == 'oci':
        if artifact['engine'] not in {'docker', 'podman'} or not re.fullmatch(r'(sha256:)?[a-f0-9]{64}', artifact['id']):
            raise StorageError('invalid immutable OCI identity; staging retained')
        process = subprocess.run([artifact['engine'], 'image', 'inspect', '--format', '{{.Id}}', artifact['id']],
                                 capture_output=True, text=True, timeout=30)
        if process.returncode or process.stdout.strip().removeprefix('sha256:') != artifact['id'].removeprefix('sha256:'):
            raise StorageError('retained OCI image unavailable; staging retained')
    else:
        raise StorageError('unknown retained artifact; staging retained')


def usage(path):
    """Logical and stat-block bytes are NOT exclusive/reclaimable extent counts."""
    path = real_path(path)
    logical = allocated = files = 0
    seen = set()
    def account(info):
        nonlocal logical, allocated, files
        key = info.st_dev, info.st_ino
        if key in seen:
            return
        seen.add(key)
        allocated += info.st_blocks * 512
        if stat.S_ISREG(info.st_mode):
            logical += info.st_size
            files += 1
    info = path.lstat()
    account(info)
    if stat.S_ISDIR(info.st_mode):
        with directory_fd(path) as root:
            for _, dirs, names, fd in os.fwalk('.', dir_fd=root, follow_symlinks=False):
                for name in dirs + names:
                    child = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if child.st_dev != info.st_dev:
                        raise StorageError('mounted subtree not measured: ' + str(path))
                    account(child)
    return {'logicalBytes': logical, 'allocatedBytes': allocated, 'files': files,
            'reclaimableBytes': None}


def inspect_context(context, *, min_age_hours=24, protected=()):
    context = real_path(context)
    result = {'path': str(context), 'category': 'build-staging', 'eligible': False}
    try:
        result['usage'] = usage(context)
        if not (context / MARKER).is_file():
            raise StorageError('untracked or incomplete build; retained (a .build suffix is not ownership evidence)')
        record = read_json(context / MARKER)
        if record.get('schemaVersion') != SCHEMA or record.get('context') != str(context) or record.get('kind') not in DISPOSABLE:
            raise StorageError('invalid storage receipt; retained')
        if record.get('status') == 'cleaned':
            result['reason'] = 'staging already cleaned; provenance retained'
            return result
        if record.get('status') != 'complete':
            raise StorageError('unfinished cleanup/build; retained')
        for value in [*protected, *protected_roots(), sys.executable, sys.prefix, sys.base_prefix]:
            path = Path(os.path.abspath(value))
            if path.is_relative_to(context) or context.is_relative_to(path):
                raise StorageError('protected state, bundle, or current interpreter overlaps staging')
        with build_lock(context, create=False):
            _verify_artifact(record['artifact'], context)
            if snapshot(context) != record['entries']:
                raise StorageError('staging changed or contains unknown files; retained')
        age = (time.time() - record['completedAt']) / 3600
        result.update(kind=record['kind'], ageHours=age)
        if age < min_age_hours:
            raise StorageError('completed build is younger than the minimum age')
        result.update(eligible=True, reason='verified completed export; package/image and provenance will be retained')
    except (OSError, ValueError, TypeError, KeyError, StorageError, subprocess.SubprocessError) as exc:
        result['reason'] = str(exc)
    return result


def prune_context(context, *, min_age_hours=24, protected=(), apply=False):
    result = inspect_context(context, min_age_hours=min_age_hours, protected=protected)
    result['removed'] = []
    if not apply or not result['eligible']:
        return result
    context = real_path(context)
    with build_lock(context, create=False):
        record = read_json(context / MARKER)
        _verify_artifact(record['artifact'], context, sync=True)
        # Revalidate after preview and under the producer's lock.
        entries = snapshot(context)
        if record.get('status') != 'complete' or entries != record['entries']:
            raise StorageError('build changed since preview; nothing removed')
        selected = {name: entry for name, entry in entries.items()
                    if Path(name).parts[0] in DISPOSABLE[record['kind']]}
        before = shutil.disk_usage(context).free
        for name in sorted(selected, key=lambda p: (len(Path(p).parts), p), reverse=True):
            path = context / name
            with directory_fd(path.parent) as parent:
                current = _entry(parent, path.name)
                # Child deletion necessarily changes a directory's mtime/size.
                if stat.S_ISDIR(current['stat'][2]):
                    if current['stat'][:3] != selected[name]['stat'][:3]:
                        raise StorageError('staging directory replaced; remaining data retained')
                    os.rmdir(path.name, dir_fd=parent)  # New/untracked files prevent removal.
                else:
                    if current != selected[name]:
                        raise StorageError('staging file changed; remaining data retained')
                    os.unlink(path.name, dir_fd=parent)
        result['removed'] = sorted({Path(name).parts[0] for name in selected})
        after = shutil.disk_usage(context).free
        record.update(status='cleaned', removed=result['removed'], freeBeforeBytes=before, freeAfterBytes=after)
        _write_marker(context, record)
        result.update(freeBeforeBytes=before, freeAfterBytes=after,
                      observedFreeChangeBytes=after-before, provenanceRetained=True)
    return result


def tool_hashes():
    spec = read_json(Path(__file__).parents[1] / 'runtime/appimage-tools.json')
    return {entry['sha256'] for group in ('runtime', 'python') for entry in spec[group].values()}


def protected_roots():
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    return [Path.home() / '.var/app', data / 'cage/appimage', data / 'cage/appimages',
            data / 'cage/package-updates']


def prune_tools(cache, *, min_age_hours=24, apply=False):
    cache = real_path(cache)
    result = {'path': str(cache), 'category': 'build-tool-cache', 'files': [], 'removed': []}
    if not cache.is_dir():
        return result
    hashes = tool_hashes()
    with (build_lock(cache) if apply else build_lock(cache, create=False) if lock_path(cache).exists() else nullcontext()):
        with directory_fd(cache) as fd:
            for name in sorted(os.listdir(fd)):
                item = {'name': name, 'eligible': False}
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if name in hashes and stat.S_ISREG(info.st_mode):
                    entry = _entry(fd, name)
                    item['eligible'] = (entry.get('sha256') == name and
                                        time.time() - info.st_mtime >= min_age_hours * 3600)
                    item['reason'] = 'verified downloadable build tool' if item['eligible'] else 'changed or too recent; retained'
                    if apply and item['eligible']:
                        if _entry(fd, name) != entry:
                            raise StorageError('tool cache changed; retained')
                        os.unlink(name, dir_fd=fd)
                        result['removed'].append(name)
                else:
                    item['reason'] = 'unknown file, directory, or runtime payload; retained'
                result['files'].append(item)
    return result


def inspect_state(path):
    result = {'path': str(path), 'category': 'application-state', 'protected': True}
    try:
        path = real_path(path)
        result['usage'] = usage(path)
        lock = path / 'launch.lock'
        result['lock'] = 'not-present'
        if lock.exists() or lock.is_symlink():
            with directory_fd(path) as fd:
                file = os.open('launch.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                if not stat.S_ISREG(os.fstat(file).st_mode):
                    raise StorageError('application lock is not a regular file; state retained')
                try:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    result['lock'] = 'idle'
                except BlockingIOError:
                    result['lock'] = 'busy'
                    result['reason'] = 'application or recovery task is running; state retained'
                    return result
                info = state_info(path, {})
            finally:
                os.close(file)
        else:
            info = state_info(path, {})
        record = info['state']
        if record and record.get('previous') and record['previous'] not in {g['prefix'] for g in record['generations']}:
            raise StorageError('previous generation is missing; restore state before rollback')
        result.update(state=record, retainedCandidates=info['retainedCandidates'])
        for name in ('prefix.partial',):
            if (path / name).exists():
                result['retainedCandidates'].append(name)
        if not record and (path / 'prefix').exists():
            result['retainedCandidates'].append('prefix')
        if (path / 'transaction.json').exists():
            transaction = read_json(path / 'transaction.json')
            committed = record and transaction.get('candidate') == record['active']
            if transaction.get('status') == 'preparing' and not committed:
                result['recovery'] = 'interrupted trial retained; state.json selects the committed generation'
        if result['retainedCandidates']:
            result['recovery'] = 'uncommitted candidate data retained; inspect saved work before recovery'
    except (OSError, ValueError, TypeError, KeyError, AttributeError, DesktopError, StorageError) as exc:
        result['error'] = str(exc)
    return result


def inspect_packages(path):
    result = {'path': str(path), 'category': 'retained-packages', 'protected': True, 'files': []}
    try:
        path = real_path(path)
        if (path / 'installation.json').exists():
            record = read_json(path / 'installation.json')
            if record.get('schemaVersion') not in {'cage.appimage-installation/v0', 'cage.appimage-installation/v1'}:
                raise StorageError('unknown installation receipt; retained')
            entries = [('application.AppImage', record['package'])]
            entries += [(e['package'], e['sha256']) for e in record.get('versions', [])]
        else:
            record = read_json(path / 'transaction.json')
            if record.get('schemaVersion') != 'cage.flatpak-update/v1':
                raise StorageError('unknown recovery receipt; retained')
            entries = [(record[key]['sha256'] + '.flatpak', record[key]['sha256']) for key in ('previous', 'candidate')]
            if record.get('status') == 'prepared':
                result['recovery'] = 'close the application, then run cage recover-flatpak on this directory'
        for name, digest in entries:
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts or not re.fullmatch(r'[a-f0-9]{64}', digest):
                raise StorageError('invalid retained package path/hash; no path followed')
            package = real_path(path / relative)
            result['files'].append({'path': str(package), 'sha256': digest, 'present': package.is_file(), 'integrity': 'not-checked'})
    except (OSError, ValueError, TypeError, KeyError, StorageError) as exc:
        result['error'] = str(exc)
    return result


def storage_status(*, output_dir='dist', index_path=None, build_dirs=(), state_dirs=(), package_dirs=(), tool_cache=None):
    output = real_path(output_dir)
    states = {Path(os.path.abspath(p)) for p in state_dirs}
    bundles, issues, ids = [], [], set()
    try:
        index_file = real_path(index_path or output / '.cage/artifacts.json')
        index = read_json(index_file) if index_file.exists() else empty_index()
        if index.get('schemaVersion') != ARTIFACT_INDEX_SCHEMA_VERSION:
            raise ArtifactIndexError('unsupported artifact index schema; retained')
        for versions in index['artifacts'].values():
            for entry in versions.values():
                path = real_path(entry['bundle'])
                if not path.is_absolute():
                    path = real_path(path)
                bundle = {'path': str(path), 'application': entry.get('application'),
                          'category': 'source-bundle', 'protected': True}
                bundles.append(bundle)
                try:
                    bundle['usage'] = usage(path)
                    manifest = read_json(path / 'manifest.cage.json')
                    app_id = manifest.get('desktop', {}).get('id')
                    if app_id:
                        ids.add(app_id)
                except (OSError, ValueError, StorageError) as exc:
                    bundle['error'] = str(exc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StorageError, RuntimeError) as exc:
        issues.append('artifact index: ' + str(exc))
    contexts = {Path(os.path.abspath(p)) for p in build_dirs}
    exports = []
    if output.is_dir():
        contexts.update(output.glob('*.build'))
        for receipt in [*output.glob('*.AppImage.json'), *output.glob('*.flatpak.json')]:
            try:
                value = read_json(receipt)
                app_id = value.get('plan', {}).get('desktop', {}).get('id')
                if app_id:
                    ids.add(app_id)
                package = real_path(str(receipt)[:-5])
                if value.get('schemaVersion') in {'cage.appimage-export-result/v0', 'cage.flatpak-export-result/v0'}:
                    exports.append({'path': str(package), 'category': 'exported-package', 'protected': True,
                                    'requiredForRecovery': False, 'files': [{'path': str(package),
                                    'sha256': value['sha256'], 'present': package.is_file(), 'integrity': 'not-checked'}],
                                    'usage': usage(package) if package.exists() else None})
            except (OSError, ValueError, KeyError, TypeError, AttributeError, StorageError) as exc:
                issues.append(str(receipt) + ': ' + str(exc))
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    package_roots = {Path(os.path.abspath(p)) for p in package_dirs}
    for base in (data / 'cage/appimage', data / 'cage/appimages', data / 'cage/package-updates/flatpak'):
        try:
            base = real_path(base)
        except StorageError as exc:
            issues.append(str(exc))
            continue
        if base.is_dir():
            ids.update(p.name for p in base.iterdir() if p.is_dir() and not p.is_symlink())
    for app_id in ids:
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+', app_id):
            issues.append('invalid application ID in receipt/index; no path followed')
            continue
        for path in (Path.home() / '.var/app' / app_id / 'data' / app_id,
                     data / 'cage/appimage' / app_id):
            if path.exists() or path.is_symlink():
                states.add(path)
        for path in (data / 'cage/appimages' / app_id, data / 'cage/package-updates/flatpak' / app_id):
            if path.exists() or path.is_symlink():
                package_roots.add(path)
    packages = exports + [inspect_packages(p) for p in sorted(package_roots)]
    protected = [Path(b['path']) for b in bundles] + list(states) + list(package_roots) + protected_roots()
    contexts_out = []
    for context in sorted(contexts):
        try:
            contexts_out.append(inspect_context(context, protected=protected))
        except (OSError, StorageError) as exc:
            contexts_out.append({'path': str(context), 'eligible': False, 'reason': str(exc)})
    state_results = [inspect_state(p) for p in sorted(states)]
    disk_path = output
    while not disk_path.exists():
        disk_path = disk_path.parent
    disk = shutil.disk_usage(disk_path)
    cache_info = None
    if tool_cache:
        cache_info = {'path': str(tool_cache), 'usage': None}
        try:
            cache = real_path(tool_cache)
            if cache.exists():
                cache_info['usage'] = usage(cache)
        except (OSError, StorageError) as exc:
            cache_info['error'] = str(exc)
            issues.append(str(exc))
    return {'schemaVersion': 'cage.storage-status/v1', 'outputDirectory': str(output),
            'disk': {'path': str(disk_path), 'totalBytes': disk.total, 'freeBytes': disk.free},
            'bundles': bundles, 'states': state_results, 'packages': packages, 'builds': contexts_out,
            'toolCache': cache_info, 'issues': issues,
            'protectedPaths': [str(p) for p in protected],
            'protection': 'all packages, installed images, runtime/runner/SDK caches, prefixes, generations and candidates are retained',
            'sizeNote': 'logical and stat-block bytes may share extents; reclaimable bytes are unknown; only disk free-space change is observed'}


def prune_storage(*, output_dir='dist', index_path=None, build_dirs=(), state_dirs=(), package_dirs=(), tool_cache=None,
                  min_age_hours=24, apply=False):
    if min_age_hours < 0 or not math.isfinite(min_age_hours):
        raise StorageError('minimum age must be a finite nonnegative number')
    status = storage_status(output_dir=output_dir, index_path=index_path, build_dirs=build_dirs,
                            state_dirs=state_dirs, package_dirs=package_dirs, tool_cache=tool_cache)
    if status['issues']:
        raise StorageError('cannot establish storage ownership/protection: ' + '; '.join(status['issues']))
    results = []
    for item in status['builds']:
        try:
            results.append(prune_context(item['path'], min_age_hours=min_age_hours,
                                         protected=status['protectedPaths'], apply=apply))
        except (OSError, ValueError, TypeError, KeyError, StorageError, subprocess.SubprocessError) as exc:
            results.append({'path': item['path'], 'eligible': False, 'removed': [], 'error': str(exc)})
    tools = None
    if tool_cache:
        cache = real_path(tool_cache)
        for path in status['protectedPaths']:
            protected = Path(path)
            if protected.is_relative_to(cache) or cache.is_relative_to(protected):
                raise StorageError('tool cache overlaps protected state/bundle; retained')
        tools = prune_tools(cache, min_age_hours=min_age_hours, apply=apply)
    return {'schemaVersion': 'cage.storage-prune/v1', 'applied': apply,
            'builds': results, 'toolCache': tools, 'issues': status['issues'],
            'userStateAndRollbackArtifactsRetained': True}


def doctor(*, required_free_mib=1024, bundle=None, **options):
    if required_free_mib < 0 or not math.isfinite(required_free_mib):
        raise StorageError('required free space must be a finite nonnegative number')
    status = storage_status(**options)
    problems = list(status['issues'])
    if status['disk']['freeBytes'] < required_free_mib * 1024**2:
        problems.append('insufficient free space for requested reserve; preview cage storage prune before rebuilding')
    for item in status['states']:
        if item.get('error'):
            problems.append(item['path'] + ': ' + item['error'])
        if item.get('recovery'):
            problems.append(item['path'] + ': ' + item['recovery'])
    for item in status['packages']:
        if item.get('error') or item.get('recovery'):
            problems.append(item['path'] + ': ' + item.get('error', item.get('recovery', '')))
        for package in item['files']:
            try:
                path = real_path(package['path'])
                with directory_fd(path.parent) as fd:
                    actual = _entry(fd, path.name).get('sha256')
                package['integrity'] = 'verified' if actual == package['sha256'] else 'changed'
            except (OSError, StorageError):
                package['integrity'] = 'unavailable'
            if package['integrity'] != 'verified' and (item.get('requiredForRecovery', True) or package['present']):
                problems.append('rollback package missing or changed; retain state and restore package: ' + package['path'])
    bundle_result = None
    if bundle:
        from artifact.index import resolve_bundle_reference
        from artifact.inspection import verify_bundle
        try:
            path = real_path(resolve_bundle_reference(str(bundle), index_path=options.get('index_path')))
            bundle_result = verify_bundle(path)
            if not bundle_result.get('runnable'):
                problems.append('selected bundle is not runnable; inspect its build status')
            if not bundle_result.get('valid'):
                problems.extend(bundle_result.get('errors', []))
            for name in ('metadata/native-launch.json', 'metadata/desktop-build.json'):
                if (path / name).is_file():
                    target = read_json(path / name).get('target', {})
                    if target.get('architecture') and target['architecture'] != platform.machine():
                        problems.append('bundle requires ' + target['architecture'] + '; host is ' + platform.machine())
                    page_sizes = target.get('translation', {}).get('hostPageSizes')
                    if page_sizes and os.sysconf('SC_PAGE_SIZE') not in page_sizes:
                        problems.append('host kernel page size is unsupported by the selected runtime')
        except (OSError, ValueError, TypeError, KeyError, AttributeError, StorageError, ArtifactIndexError) as exc:
            problems.append('selected bundle: ' + str(exc))
    return {'schemaVersion': 'cage.diagnostics/v1', 'healthy': not problems, 'problems': problems,
            'host': {'os': platform.system(), 'architecture': platform.machine(), 'pageSize': os.sysconf('SC_PAGE_SIZE')},
            'tools': {name: shutil.which(name) for name in ('flatpak', 'podman', 'docker', 'mksquashfs', 'readelf')},
            'storage': status, 'bundleVerification': bundle_result,
            'note': 'reserve is a user-selected floor, not an estimate that a full Wine copy or Flatpak deployment will fit'}
