"""Native AppDir adapter over the sealed desktop plan; no application installer logic."""
from __future__ import annotations

from artifact.storage import build_lock, record_export

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

from artifact.desktop import create_desktop_export_plan, stage_desktop_fonts, stage_notices
from artifact.flatpak import ICON
from builder.flatpak import ensure_target, initialize_flatpak, run_flatpak
from runtime import desktop_launch
from runtime.desktop_launch import DesktopError, digest_json, inventory_tree, verify_inventory
from runtime.appimage_runtime import INTERPRETER_PLACEHOLDER, interpreter_slot

ROOT = Path(__file__).resolve().parents[1]
# glibc and its matching loader come from the same pinned platform as the closure.
LIBC_LIBRARIES = {'libc.so.6', 'libm.so.6', 'libresolv.so.2', 'libdl.so.2',
                  'libmvec.so.1', 'ld-linux-x86-64.so.2', 'ld-linux-aarch64.so.1',
                  'libpthread.so.0', 'librt.so.1', 'libutil.so.1', 'libanl.so.1'}
HOST_LIBRARIES = {'libGL.so.1', 'libEGL.so.1', 'libvulkan.so.1', 'libva.so.2', 'libva-drm.so.2'}
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
    managed = source.get('state', {}).get('managerVersion') == 2
    if not managed and not allow_host_access:
        raise DesktopError('AppImage cannot enforce runtime.network: none or filesystem isolation; '
                           'export requires --allow-host-access to explicitly accept ordinary host-process access')
    lock = tools_lock()
    target = {**source['target'], 'id': 'appimage-' + source['target']['id'],
        'format': 'appimage', 'sourceTargetDigest': digest_json(source['target']),
        'privateRuntime': lock['privateRuntime'], 'toolsDigest': digest_json(lock),
        'excludedUnixModules': lock['excludedUnixModules'],
        'wineDllDirectory': ('lib64/wine-wow64/wine' if source['target']['provider'] == 'wine-arm64ec' else 'lib/wine')}
    plan = {**source, 'target': target, 'sourceTarget': source['target'], 'format': 'appimage',
        'layout': {'runtime': 'usr/wine'},
        'state': {**source['state'], 'namespace': 'cage/appimage',
                  'packagerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'integrationSha256': hashlib.sha256((ROOT / 'runtime/appimage_launch.py').read_bytes()).hexdigest(),
                  'privateRuntimeSha256': hashlib.sha256((ROOT / 'runtime/appimage_runtime.py').read_bytes()).hexdigest()},
        'permissions': {'isolation': 'none', 'network': 'host', 'filesystem': 'host-user',
                        'explicitHostAccessAccepted': True, 'recipeNetworkPolicyEnforced': False},
        'tools': lock, 'prerequisites': ['Linux ' + target['architecture'],
             'X11/XWayland; FUSE or extraction fallback; executable temporary storage'],
        'distribution': 'local unsigned proof; application compatibility is qualified separately'}
    if managed:
        from core.capabilities import compile_capabilities, require_supported
        from runtime.appimage_runtime import MATERIALIZER_ABI
        capabilities = compile_capabilities(source['recipe'], 'appimage')
        require_supported(capabilities)
        plan.update(capabilities=capabilities, managedNamespace=True, materializerABI=MATERIALIZER_ABI,
                    permissions={'isolation':'cage.local-desktop/v1','hostCageRequired':True},
                    layout={'runtime':'/run/cage/native/usr/wine'},
                    prerequisites=['native Linux x86_64', 'host Cage', 'Bubblewrap', 'SquashFS tools >= 4.6.1', 'qualified user namespace and LSM policy'])
    return plan


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



def omit_unqualified_modules(wine_root, names):
    omitted = []
    for name in names:
        if name != 'winedmo.so':
            raise DesktopError('unknown AppImage module exclusion')
        for path in Path(wine_root).rglob(name):
            if not path.parent.name.endswith('-unix') or path.is_symlink():
                raise DesktopError('unexpected location for an excluded Unix module')
            with path.open('rb') as handle:
                sha = hashlib.file_digest(handle, 'sha256').hexdigest()
            omitted.append({'path': str(path.relative_to(wine_root)), 'sha256': sha,
                            'reason': 'DirectShow media decoding is outside the X11 desktop proof'})
            path.unlink()
    return omitted


def relocate_wine_links(wine_root):
    wine_root = Path(wine_root).resolve()
    result = []
    for path in wine_root.rglob('*'):
        if not path.is_symlink() or not os.path.isabs(os.readlink(path)):
            continue
        original = Path(os.readlink(path))
        if not original.is_relative_to('/app'):
            raise DesktopError('non-portable Wine payload link: ' + str(original))
        target = wine_root / original.relative_to('/app')
        if not target.resolve().is_relative_to(wine_root) or not target.is_file():
            raise DesktopError('unresolved Wine payload link: ' + str(original))
        path.unlink()
        path.symlink_to(os.path.relpath(target, path.parent))
        result.append({'path': str(path.relative_to(wine_root)), 'originalTarget': str(original),
                       'target': os.readlink(path)})
    return result


def platform_directory(platform_root, relative):
    """Resolve /usr links inside the pinned platform, never on the build host."""
    platform_root = Path(platform_root).resolve()
    path = platform_root / relative
    for _ in range(8):
        if not path.is_symlink():
            break
        target = Path(os.readlink(path))
        if target.is_absolute():
            if not target.is_relative_to('/usr'):
                raise DesktopError('unexpected platform data link: ' + str(target))
            path = platform_root / target.relative_to('/usr')
        else:
            path = path.parent / target
    if not path.resolve().is_relative_to(platform_root) or not path.is_dir():
        raise DesktopError('missing or escaping pinned platform data: ' + relative)
    return path


def stage_native_libraries(appdir, platform_root, minimum_glibc):
    """Resolve ELF imports without executing ldd, plus the qualified X11 dlopens."""
    appdir, platform_root = Path(appdir), Path(platform_root)
    native = appdir / 'usr/lib/cage-native'
    native.mkdir(parents=True)
    triplet = {'x86_64': 'x86_64-linux-gnu', 'aarch64': 'aarch64-linux-gnu'}[platform.machine()]
    platform_libraries = platform_root / 'lib' / triplet
    available = {}
    # The x86 Wine base carries additional private dependencies (e.g. Kerberos)
    # absent from the platform. Honor their SONAME symlink aliases and preserve
    # the producer's dependency precedence before falling back to the platform.
    for source in (appdir / 'usr/wine', platform_libraries):
        for path in sorted(source.rglob('*.so*')):
            if path.is_file() and path.resolve().is_relative_to(source.resolve()):
                available.setdefault(path.name, path)
    # Never mix the Wine base's libc with a different platform loader.
    for name in LIBC_LIBRARIES | {'libnss_dns.so.2', 'libnss_files.so.2'}:
        path = platform_libraries / name
        if path.is_file():
            available[name] = path
    internal = {}
    queue = []
    for base in (appdir / 'usr/wine', appdir / 'usr/python'):
        for path in base.rglob('*'):
            if path.is_file() and not path.is_symlink() and elf_information(path):
                queue.append(path)
                if base.name == 'wine':
                    internal[path.name] = path
    for name in [*DYNAMIC_LIBRARIES, *sorted(LIBC_LIBRARIES & available.keys()),
                 *sorted({'libnss_dns.so.2', 'libnss_files.so.2'} & available.keys())]:
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


def stage_private_runtime(appdir, platform_root, architecture):
    """Reserve relocatable interpreter slots and bind every native ELF to libc."""
    appdir, platform_root = Path(appdir), Path(platform_root)
    loader = {'x86_64': 'ld-linux-x86-64.so.2', 'aarch64': 'ld-linux-aarch64.so.1'}[architecture]
    triplet = {'x86_64': 'x86_64-linux-gnu', 'aarch64': 'aarch64-linux-gnu'}[architecture]
    native = appdir / 'usr/lib/cage-native'
    source = platform_root / 'lib' / triplet / loader
    if not source.is_file() or not source.resolve().is_relative_to(platform_root.resolve()):
        raise DesktopError('missing or escaping pinned glibc loader')
    copy_file(source.resolve(), native / loader)
    if not (native / 'libc.so.6').is_file():
        raise DesktopError('private runtime requires pinned libc.so.6')
    gconv = platform_root / 'lib' / triplet / 'gconv'
    if gconv.is_dir():
        shutil.copytree(gconv, native / 'gconv', symlinks=True, copy_function=copy_file)
    files = []
    for base in (appdir / 'usr/wine', appdir / 'usr/python', native):
        for path in sorted(base.rglob('*')):
            if path.is_symlink() or not path.is_file():
                continue
            info = elf_information(path)
            if not info:
                continue
            # The loader relocates itself before normal dependency lookup;
            # rewriting its dynamic section can break that bootstrap. Keep
            # the matching glibc family byte-for-byte from the platform.
            if not (path.parent == native and path.name in LIBC_LIBRARIES) and (info['needed'] or interpreter_slot(path)):
                # Keep existing relative paths for Wine/Python's private modules.
                old = subprocess.check_output(['patchelf', '--print-rpath', str(path)], text=True).strip()
                private = '$ORIGIN/' + os.path.relpath(native, path.parent)
                paths = [private, *(p for p in old.split(':') if p.startswith('$ORIGIN'))]
                args = ['patchelf', '--force-rpath', '--set-rpath', ':'.join(dict.fromkeys(paths))]
                if interpreter_slot(path):
                    args += ['--set-interpreter', INTERPRETER_PLACEHOLDER]
                subprocess.run([*args, str(path)], check=True, capture_output=True)
            slot = interpreter_slot(path)
            # Wine canonicalizes ntdll.so to locate child loaders. Every native
            # ELF must retain launch-tree identity, including shared libraries.
            files.append({'path': str(path.relative_to(appdir)), 'interpreter': bool(slot) and path.name not in LIBC_LIBRARIES,
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {'schemaVersion': 'cage.appimage-private-runtime/v1',
                'loader': 'usr/lib/cage-native/' + loader, 'files': files}
    (appdir / 'usr/libexec/private-runtime.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


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
    relocated = relocate_wine_links(appdir / 'usr/wine')
    omitted = omit_unqualified_modules(appdir / 'usr/wine', plan['target']['excludedUnixModules'])
    arch = plan['target']['architecture']
    unpack_python(checked_download(plan['tools']['python'][arch], cache), appdir / 'usr')
    location = run_flatpak(['info', '--user', '--show-location',
        plan['sourceTarget']['platform'] + '/' + arch + '/' + plan['sourceTarget']['branch']], store=store)
    closure = stage_native_libraries(appdir, Path(location) / 'files', plan['tools']['privateRuntime']['maximumGlibc'])
    closure['omittedUnixModules'] = omitted
    closure['relocatedWineLinks'] = relocated
    stage_desktop_fonts(appdir / 'usr', Path(location) / 'files')
    for directory in ('locale', 'xkb'):
        # New xkeyboard-config uses a sibling directory and an X11 symlink.
        # Materialize its data here rather than retaining a dangling link.
        shutil.copytree(platform_directory(Path(location) / 'files', 'share/X11/' + directory),
                        appdir / 'usr/share/X11' / directory, symlinks=True, copy_function=copy_file)
    helpers = appdir / 'usr/libexec'
    helpers.mkdir(parents=True)
    for name in ['desktop_launch.py', 'appimage_launch.py', 'appimage_runtime.py']:
        shutil.copyfile(ROOT / 'runtime' / name, helpers / name)
        expected = plan['state'][{'desktop_launch.py': 'launcherSha256',
                                  'appimage_launch.py': 'integrationSha256',
                                  'appimage_runtime.py': 'privateRuntimeSha256'}[name]]
        if hashlib.sha256((helpers / name).read_bytes()).hexdigest() != expected:
            raise DesktopError('lifecycle helper changed after export planning')
    if plan.get('managedNamespace'):
        shutil.copyfile(ROOT/'runtime/capability_guard.py', helpers/'capability_guard.py')
    # -I excludes host Python paths; only the one packaged helper directory is added.
    (helpers / 'entry.py').write_text('import sys\nfrom pathlib import Path\n'
        'sys.path.insert(0, str(Path(__file__).resolve().parent))\n'
        'from appimage_runtime import bootstrap\nbootstrap()\n')
    closure['privateRuntime'] = stage_private_runtime(appdir, Path(location) / 'files', arch)
    # Hashes describe the final patched payload, including libc and its loader.
    closure['libraries'] = inventory_tree(appdir / 'usr/lib/cage-native')
    if plan.get('managedNamespace'):
        # Final closure identity includes both patched native executables and
        # dependency bytes. Temporary materialization paths are excluded.
        plan['runtimeClosureDigest'] = digest_json({'privateRuntime':closure['privateRuntime'], 'libraries':closure['libraries']})
        (destination/'desktop.json').write_text(json.dumps(plan, indent=2, sort_keys=True)+'\n')
    (appdir / 'AppRun').write_text(apprun_script(plan))
    (appdir / 'AppRun').chmod(0o755)
    (appdir / (app_id + '.svg')).write_text(ICON)
    (appdir / '.DirIcon').symlink_to(app_id + '.svg')
    (appdir / (app_id + '.desktop')).write_text(desktop_launch.desktop_entry(plan, 'AppRun -- %F'))
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
    if plan.get('managedNamespace'):
        # A v1 package cannot bootstrap artifact Python in the host namespace.
        # Installation/launch uses the host CLI and its verified release ledger.
        return '#!/bin/sh\necho "Import and run this managed v1 AppImage with host-installed cage release." >&2\nexit 1\n'
    arch = plan['target']['architecture']
    loader = {'x86_64': 'ld-linux-x86-64.so.2', 'aarch64': 'ld-linux-aarch64.so.1'}[arch]
    return f'''#!/bin/sh
set -eu
if [ "$(uname -m)" != "{arch}" ]; then
    echo "Cage AppImage requires Linux {arch}." >&2; exit 1
fi
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
unset PYTHONHOME PYTHONPATH LD_LIBRARY_PATH LD_PRELOAD LD_AUDIT
exec "$HERE/usr/lib/cage-native/{loader}" --inhibit-cache \\
    --library-path "$HERE/usr/python/lib:$HERE/usr/lib/cage-native" \\
    --argv0 "$HERE/usr/python/bin/python3" "$HERE/usr/python/bin/python3" \\
    -I "$HERE/usr/libexec/entry.py" "$HERE" "$@"
'''


def export_appimage(bundle, *, output, store, allow_host_access=False, context_dir=None,
                    cache='.cage/appimage-tools', timeout=1800):
    plan = create_appimage_export_plan(bundle, allow_host_access=allow_host_access)
    if platform.system() != 'Linux' or platform.machine() != plan['target']['architecture']:
        raise DesktopError('AppImage export requires a native Linux build runner for ' + plan['target']['architecture'])
    for executable in ('readelf', 'patchelf', 'mksquashfs', 'flatpak'):
        if not shutil.which(executable):
            raise DesktopError('AppImage producer requires ' + executable + ' (not needed by consumers)')
    output = Path(output).resolve()
    if output.is_relative_to(Path(bundle).resolve()) or output.exists() or Path(str(output) + '.partial').exists():
        raise DesktopError('AppImage output must be new and outside the source bundle')
    output.parent.mkdir(parents=True, exist_ok=True)
    context = Path(context_dir).resolve() if context_dir else output.parent / (output.name + '.build')
    cache = Path(cache).resolve()
    with build_lock(context), build_lock(cache):
        appdir = prepare_appdir(bundle, plan, context, store=store, cache=cache)
        runtime = checked_download(plan['tools']['runtime'][plan['target']['architecture']], cache)
        squashfs = context / 'payload.squashfs'
        try:
            result = subprocess.run(['mksquashfs', str(appdir), str(squashfs), '-noappend', '-all-root',
                '-comp', 'zstd', '-processors', '2', '-no-progress'], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise DesktopError('mksquashfs exceeded the export timeout; staging retained') from exc
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
            'context': str(context.resolve()), 'plan': plan,
            'patchelfVersion': subprocess.check_output(['patchelf', '--version'], text=True).strip(),
            'mksquashfsVersion': subprocess.check_output(['mksquashfs', '-version'], text=True).splitlines()[0]}
        Path(str(output) + '.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        result['storage'] = record_export(context, bundle, 'appimage', {'kind': 'file', 'path': str(output), 'sha256': result['sha256']})
        return result
