"""Native AppDir adapter over the sealed desktop plan; no application installer logic."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from artifact.desktop import create_desktop_export_plan
from artifact.flatpak import ICON
from builder.flatpak import ensure_target, initialize_flatpak, run_flatpak
from runtime import desktop_launch
from runtime.desktop_launch import DesktopError, digest_json, inventory_tree, verify_inventory

ROOT = Path(__file__).resolve().parents[1]
# The host owns glibc/loader and graphics drivers. Never ship a second libc.
HOST_LIBRARIES = {'libc.so.6', 'libm.so.6', 'libresolv.so.2', 'libdl.so.2',
                  'libpthread.so.0', 'librt.so.1', 'libutil.so.1', 'libanl.so.1',
                  'libGL.so.1', 'libEGL.so.1', 'libvulkan.so.1', 'libva.so.2', 'libva-drm.so.2'}
# These optional Wine subsystems already lack native dependencies in the selected
# Flatpak payload. Keep the modules, disclose the limit; do not resolve from host.
OPTIONAL_MODULES = {'gphoto2.so', 'kerberos.so', 'wpcap.so'}
DYNAMIC_LIBRARIES = ['libfontconfig.so.1', 'libfreetype.so.6', 'libX11.so.6',
    'libXcursor.so.1', 'libXrandr.so.2', 'libXrender.so.1', 'libXext.so.6',
    'libXi.so.6', 'libXfixes.so.3', 'libXinerama.so.1', 'libXcomposite.so.1',
    'libXxf86vm.so.1', 'libgnutls.so.30', 'libdbus-1.so.3', 'libudev.so.1']


def tools_lock():
    return json.loads((ROOT / 'runtime/appimage-tools.json').read_text())


def create_appimage_export_plan(bundle, *, allow_host_access=False):
    source = create_desktop_export_plan(bundle)
    if not allow_host_access:
        raise DesktopError('AppImage cannot enforce runtime.network: none or filesystem isolation; '
                           'export requires --allow-host-access to explicitly accept ordinary host-process access')
    lock = tools_lock()
    target = {**source['target'], 'id': 'appimage-' + source['target']['id'],
        'format': 'appimage', 'sourceTargetDigest': digest_json(source['target']),
        'minimumGlibc': lock['minimumGlibc'], 'toolsDigest': digest_json(lock),
        'wineDllDirectory': ('lib64/wine-wow64/wine' if source['target']['provider'] == 'wine-arm64ec' else 'lib/wine')}
    return {**source, 'target': target, 'sourceTarget': source['target'], 'format': 'appimage',
        'layout': {'runtime': 'usr/wine'},
        'state': {**source['state'], 'namespace': 'cage/appimage'},
        'permissions': {'isolation': 'none', 'network': 'host', 'filesystem': 'host-user',
                        'explicitHostAccessAccepted': True, 'recipeNetworkPolicyEnforced': False},
        'tools': lock, 'prerequisites': ['Linux ' + target['architecture'],
             'glibc >= ' + lock['minimumGlibc'], 'X11/XWayland; FUSE or extraction fallback'],
        'distribution': 'local unsigned proof; application compatibility is qualified separately'}


def checked_download(spec, cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / spec['sha256']
    if not path.exists():
        fd, name = tempfile.mkstemp(prefix='.download-', dir=cache)
        try:
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(spec['url'], timeout=120) as response:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 128 * 1024 * 1024:
                        raise DesktopError('AppImage tool download exceeds its size limit')
                    output.write(chunk)
            Path(name).replace(path)
        finally:
            Path(name).unlink(missing_ok=True)
    with path.open('rb') as handle:
        actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if actual != spec['sha256']:
        raise DesktopError('AppImage tool checksum mismatch: ' + str(path))
    return path


def copy_file(source, destination):
    """Reflink large immutable seeds where supported; ordinary copy elsewhere."""
    import fcntl
    try:
        with open(source, 'rb') as src, open(destination, 'wb') as dst:
            fcntl.ioctl(dst, 0x40049409, src.fileno())  # FICLONE
    except OSError:
        shutil.copyfile(source, destination)
    shutil.copystat(source, destination)
    return destination


def unpack_python(archive, destination):
    with tarfile.open(archive, 'r:gz') as handle:
        members = handle.getmembers()
        if sum(m.size for m in members) > 512 * 1024 * 1024 or len(members) > 20000:
            raise DesktopError('standalone Python archive exceeds extraction limits')
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[:1] != ('python',):
                raise DesktopError('unsafe standalone Python archive path')
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()) or member.mode & 0o6000:
                raise DesktopError('unsafe standalone Python archive member')
        handle.extractall(destination, filter='data')
    inventory_tree(Path(destination) / 'python')


def elf_information(path):
    with Path(path).open('rb') as handle:
        if handle.read(4) != b'\x7fELF':
            return None
    result = subprocess.run(['readelf', '-d', '-V', str(path)], text=True, capture_output=True, check=True)
    needs = result.stdout.split('Version needs section', 1)[-1] if 'Version needs section' in result.stdout else ''
    return {'needed': re.findall(r'Shared library: \[(.*?)\]', result.stdout),
            'glibc': re.findall(r'GLIBC_([0-9]+\.[0-9]+)', needs)}


def stage_native_libraries(appdir, platform_root, minimum_glibc):
    """Resolve ELF imports without executing ldd, plus the qualified X11 dlopens."""
    appdir, platform_root = Path(appdir), Path(platform_root)
    native = appdir / 'usr/lib/cage-native'
    native.mkdir(parents=True)
    available = {}
    for path in sorted((platform_root / 'lib').rglob('*.so*')):
        if path.is_file() and path.resolve().is_relative_to(platform_root.resolve()):
            available.setdefault(path.name, path)
    internal = {}
    queue = []
    for base in (appdir / 'usr/wine', appdir / 'usr/python'):
        for path in base.rglob('*'):
            if path.is_file() and not path.is_symlink() and elf_information(path):
                queue.append(path)
                if base.name == 'wine':
                    internal[path.name] = path
    for name in DYNAMIC_LIBRARIES:
        if name not in available:
            raise DesktopError('missing qualified X11 runtime dependency: ' + name)
        destination = native / name
        copy_file(available[name].resolve(), destination)
        queue.append(destination)
    seen, missing, maximum = set(), [], (0, 0)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        info = elf_information(path)
        if not info:
            continue
        for version in info['glibc']:
            maximum = max(maximum, tuple(map(int, version.split('.'))))
        for name in info['needed']:
            if name.startswith('$ORIGIN/'):
                resolved = path.parent / name.removeprefix('$ORIGIN/')
                if not resolved.resolve().is_relative_to(appdir.resolve()) or not resolved.is_file():
                    raise DesktopError('unresolved relative native dependency: ' + name)
                queue.append(resolved.resolve())
                continue
            if '/' in name:
                raise DesktopError('non-relocatable native dependency: ' + name)
            if name in HOST_LIBRARIES or name in internal:
                continue
            # Standalone Python carries its own private library directory.
            if path.is_relative_to(appdir / 'usr/python') and list((appdir / 'usr/python/lib').glob(name)):
                continue
            destination = native / name
            if destination.exists():
                continue
            if name not in available:
                if path.name in OPTIONAL_MODULES:
                    missing.append({'module': str(path.relative_to(appdir)), 'library': name})
                    continue
                raise DesktopError('unresolved native dependency ' + name + ' for ' + str(path))
            copy_file(available[name].resolve(), destination)
            queue.append(destination)
    if maximum > tuple(map(int, minimum_glibc.split('.'))):
        raise DesktopError('payload exceeds declared glibc baseline: ' + '.'.join(map(str, maximum)))
    return {'maximumRequiredGlibc': '.'.join(map(str, maximum)),
            'hostLibraries': sorted(HOST_LIBRARIES), 'unqualifiedOptionalModules': missing,
            'libraries': inventory_tree(native)}


def prepare_appdir(bundle, plan, context, *, store, cache):
    context, bundle = Path(context).resolve(), Path(bundle).resolve()
    if context.is_relative_to(bundle) or context.exists():
        raise DesktopError('AppImage staging must be a new directory outside the source bundle')
    context.mkdir(parents=True)
    appdir = context / 'AppDir'
    app_id = plan['desktop']['id']
    destination = appdir / 'usr/share/cage' / app_id
    destination.mkdir(parents=True)
    receipt = json.loads((bundle / 'metadata/desktop-build.json').read_text())
    if digest_json(receipt['inventory']) != plan['seedDigest']:
        raise DesktopError('source inventory changed after planning')
    shutil.copytree(bundle / 'prefix', destination / 'seed', symlinks=True, copy_function=copy_file)
    verify_inventory(destination / 'seed', receipt['inventory'])
    manifest = json.loads((bundle / 'manifest.cage.json').read_text())
    if digest_json(manifest) != plan['sourceManifestDigest']:
        raise DesktopError('source manifest changed after planning')
    for name, value in [('desktop.json', plan), ('seed-inventory.json', receipt['inventory']),
                         ('manifest.cage.json', manifest)]:
        (destination / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    # Reuse the identical Wine producer and package bytes, not its root filesystem.
    ensure_target(plan['sourceTarget'], store)
    wine_stage = context / 'wine-target'
    initialize_flatpak(wine_stage, app_id, plan['sourceTarget'], store)
    (wine_stage / 'files').rename(appdir / 'usr/wine')
    shutil.rmtree(wine_stage)
    arch = plan['target']['architecture']
    unpack_python(checked_download(plan['tools']['python'][arch], cache), appdir / 'usr')
    location = run_flatpak(['info', '--user', '--show-location',
        plan['sourceTarget']['platform'] + '/' + arch + '/' + plan['sourceTarget']['branch']], store=store)
    closure = stage_native_libraries(appdir, Path(location) / 'files', plan['target']['minimumGlibc'])
    fonts = Path(location) / 'files/share/fonts'
    shutil.copytree(fonts / 'dejavu', appdir / 'usr/share/fonts', copy_function=copy_file)
    for directory in ('locale', 'xkb'):
        # New xkeyboard-config uses a sibling directory and an X11 symlink.
        # Materialize its data here rather than retaining a dangling link.
        shutil.copytree((Path(location) / 'files/share/X11' / directory).resolve(),
                        appdir / 'usr/share/X11' / directory, symlinks=True, copy_function=copy_file)
    notices = Path(location) / 'files/share/licenses'
    if not notices.is_dir():
        raise DesktopError('pinned platform is missing its dependency license notices')
    shutil.copytree(notices, appdir / 'usr/share/licenses/freedesktop', symlinks=True, copy_function=copy_file)
    (appdir / 'usr/share/cage/fonts.conf').write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
        '<fontconfig><dir prefix="relative">../fonts</dir><cachedir prefix="xdg">fontconfig</cachedir></fontconfig>\n')
    helpers = appdir / 'usr/libexec'
    helpers.mkdir(parents=True)
    for name in ['desktop_launch.py', 'appimage_launch.py']:
        shutil.copyfile(ROOT / 'runtime' / name, helpers / name)
    # -I excludes host Python paths; only the one packaged helper directory is added.
    (helpers / 'entry.py').write_text('import sys\nfrom pathlib import Path\n'
        'sys.path.insert(0, str(Path(__file__).resolve().parent))\n'
        'import runpy\nrunpy.run_module("appimage_launch", run_name="__main__")\n')
    (appdir / 'AppRun').write_text(apprun_script(plan))
    (appdir / 'AppRun').chmod(0o755)
    (appdir / (app_id + '.svg')).write_text(ICON)
    (appdir / '.DirIcon').symlink_to(app_id + '.svg')
    (appdir / (app_id + '.desktop')).write_text('[Desktop Entry]\nType=Application\nName='
        + plan['desktop']['name'].replace('\\', '\\\\') + '\nExec=AppRun %F\nIcon=' + app_id
        + '\nCategories=' + ';'.join(plan['desktop']['categories']) + ';\nTerminal=false\n')
    (destination / 'native-dependencies.json').write_text(json.dumps(closure, indent=2, sort_keys=True) + '\n')
    (destination / 'component-sources.json').write_text(json.dumps({
        'applicationSources': manifest.get('sources', []), 'applicationLicense': plan['desktop']['license'],
        'wineTarget': plan['sourceTarget'], 'appimageTools': plan['tools'],
        'nativeDependencySource': 'Freedesktop platform OSTree commit ' + plan['sourceTarget']['platformCommit'],
        'notice': 'Preserve notices and provide corresponding sources before redistribution; no publication performed.'
    }, indent=2, sort_keys=True) + '\n')
    (context / 'export-plan.json').write_text(json.dumps(plan, indent=2, sort_keys=True) + '\n')
    (context / 'appdir-inventory.json').write_text(json.dumps(inventory_tree(appdir), sort_keys=True) + '\n')
    return appdir


def apprun_script(plan):
    arch = plan['target']['architecture']
    major, minor = plan['target']['minimumGlibc'].split('.')
    return f'''#!/bin/sh
set -eu
if [ "$(uname -m)" != "{arch}" ]; then
    echo "Cage AppImage requires Linux {arch}." >&2; exit 1
fi
libc=$(getconf GNU_LIBC_VERSION 2>/dev/null) || {{ echo "Cage AppImage requires glibc {major}.{minor} or later." >&2; exit 1; }}
version=${{libc#glibc }}
first=${{version%%.*}}; second=${{version#*.}}; second=${{second%%.*}}
if [ "$first" -lt {major} ] || {{ [ "$first" -eq {major} ] && [ "$second" -lt {minor} ]; }}; then
    echo "Cage AppImage requires glibc {major}.{minor} or later; found $version." >&2; exit 1
fi
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
unset PYTHONHOME PYTHONPATH LD_PRELOAD LD_AUDIT
LD_LIBRARY_PATH="$HERE/usr/python/lib:$HERE/usr/lib/cage-native"
export LD_LIBRARY_PATH
exec "$HERE/usr/python/bin/python3" -I "$HERE/usr/libexec/entry.py" "$HERE" "$@"
'''


def export_appimage(bundle, *, output, store, allow_host_access=False, context_dir=None,
                    cache='.cage/appimage-tools', timeout=1800):
    plan = create_appimage_export_plan(bundle, allow_host_access=allow_host_access)
    if platform.system() != 'Linux' or platform.machine() != plan['target']['architecture']:
        raise DesktopError('AppImage export requires a native Linux build runner for ' + plan['target']['architecture'])
    output = Path(output).resolve()
    if output.is_relative_to(Path(bundle).resolve()) or output.exists() or Path(str(output) + '.partial').exists():
        raise DesktopError('AppImage output must be new and outside the source bundle')
    output.parent.mkdir(parents=True, exist_ok=True)
    context = Path(context_dir) if context_dir else output.parent / (output.name + '.build')
    appdir = prepare_appdir(bundle, plan, context, store=store, cache=cache)
    runtime = checked_download(plan['tools']['runtime'][plan['target']['architecture']], cache)
    squashfs = context / 'payload.squashfs'
    result = subprocess.run(['mksquashfs', str(appdir), str(squashfs), '-noappend', '-all-root',
        '-comp', 'zstd', '-processors', '2', '-no-progress'], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise DesktopError('mksquashfs failed: ' + result.stderr[-4000:])
    partial = Path(str(output) + '.partial')
    try:
        with partial.open('xb') as handle, runtime.open('rb') as first, squashfs.open('rb') as second:
            shutil.copyfileobj(first, handle)
            shutil.copyfileobj(second, handle)
        partial.chmod(0o755)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    with output.open('rb') as handle:
        sha = hashlib.file_digest(handle, 'sha256').hexdigest()
    result = {'schemaVersion': 'cage.appimage-export-result/v0', 'success': True,
        'output': str(output), 'sha256': sha, 'bytes': output.stat().st_size,
        'context': str(context.resolve()), 'plan': plan, 'mksquashfsVersion': subprocess.check_output(['mksquashfs', '-version'], text=True).splitlines()[0]}
    Path(str(output) + '.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result
