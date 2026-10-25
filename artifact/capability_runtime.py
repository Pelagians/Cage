"""Host-side capability resolution shared by the three managed adapters."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import stat

from artifact import authority, releases as r
from core.capabilities import compile_capabilities, digest, require_supported
from artifact.permissions import local_bindings, applicable_inputs, resolve_location, native_snapshot, path_access, native_filesystems, _native_path, overlapping_native_grants


def protected_paths(app, root=None):
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', home/'.local/share'))
    config = Path(os.environ.get('XDG_CONFIG_HOME', home/'.config'))
    cache = Path(os.environ.get('XDG_CACHE_HOME', home/'.cache'))
    paths=[data/'cage', config/'cage', cache/'cage', home/'.var/app',
           data/'applications',config/'autostart',config/'systemd/user',home/'.local/bin',Path(__file__).resolve().parents[1],
           *([Path(root)] if root else [])]
    registry=data/'cage/releases/installed'
    if registry.is_dir():
        # Reuse canonical authority records: another format/cache cannot turn a
        # policy or recovery store into an apparently ordinary folder grant.
        for folder in registry.iterdir():
            if not folder.is_dir() and not folder.is_symlink():continue
            owner=authority.read_authority(folder.name)
            for kind,entry in (owner or {}).get('formats',{}).items():
                ledger=Path(entry['ledgerRoot']);paths.append(ledger)
                installed=ledger/'installed'/folder.name/kind/'installation.json'
                if installed.is_file():
                    record=r.parse(r.small(r.regular(installed)))
                    if record.get('publisherKeySha256')!=owner['publisherKeySha256']:raise r.ReleaseError('canonical/format authority conflict; reconcile before launch')
                    if record.get('stateDirectory'):paths.append(Path(record['stateDirectory']))
    return paths


def overlaps(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or a in b.parents or b in a.parents


def resolve_files(plan, app, root=None, *, create=False):
    """Validate host aliases too; a symbolic base is never an access boundary."""
    paths = []
    for item in plan['requests']:
        request = item['resolved']
        if request['kind'] != 'filesystem': continue
        path = resolve_location(request['location'])
        resolved = path.resolve()
        if any(overlaps(resolved, p) for p in protected_paths(app, root)):
            raise r.ReleaseError('folder exposes protected Cage/native application state or recovery data')
        # Flatpak and OCI reserve these namespace trees, irrespective of host aliases.
        if any(resolved == Path(p) or Path(p) in resolved.parents for p in ('/dev','/proc','/sys','/run','/app','/usr','/etc','/var','/opt')):
            raise r.ReleaseError('folder resolves into a reserved runtime namespace')
        entry = {'id':item['id'],'host':str(resolved),'access':request['access'],
                 'granted':item['grant'] is not None,'intentGranted':item['grant'] is not None,'wineDrive':request.get('wineDrive')}
        if item['grant']:
            if not path.exists():
                if request['create'] and create:
                    path.mkdir(parents=True, mode=0o700)
                elif request['create']:
                    entry['creationPending']=True
                elif request['required']:
                    raise r.ReleaseError('required folder unavailable: ' + str(path))
                else:
                    entry['granted'] = False
            if path.exists() and (not path.is_dir() or not os.access(path, os.R_OK | (os.W_OK if request['access']=='read-write' else 0))):
                raise r.ReleaseError('folder lacks required host authorization: ' + str(path))
            if entry['granted'] and path.exists():
                info=path.stat();entry.update(device=info.st_dev,inode=info.st_ino)
        paths.append(entry)
    for i,a in enumerate(paths):
        for b in paths[i+1:]:
            if overlaps(a['host'], b['host']) and (a['granted'] != b['granted'] or a['access'] != b['access']):
                raise r.ReleaseError('resolved folder aliases defeat a denial/read-only grant')
    return paths


def grants(plan, kind):
    return [item for item in plan['requests'] if item['grant'] and item['grant']['kind'] == kind]


def all_devices(plan):
    return any(item['grant'] and (item['grant'].get('class') == 'all' or item['fallback']) for item in plan['requests'])


def x11():
    display = os.environ.get('DISPLAY', '')
    match = re.fullmatch(r':([0-9]+)(?:\.[0-9]+)?', display)
    if not match:
        raise r.ReleaseError('v1 X11 requires a local Unix display; remote displays remain unqualified')
    socket = Path('/tmp/.X11-unix/X' + match[1])
    if not socket.exists() or not stat.S_ISSOCK(socket.stat().st_mode):
        raise r.ReleaseError('local X11 socket unavailable')
    auth = Path(os.environ.get('XAUTHORITY', str(Path.home()/'.Xauthority')))
    if not auth.is_file() or auth.is_symlink():
        raise r.ReleaseError('v1 requires a readable regular Xauthority file')
    return {'display':display,'socket':str(socket),'authority':str(auth.absolute())}


def native_policy(release, capabilities, paths, root=None):
    snapshot = native_snapshot(release)
    context = snapshot['policy'].get('Context', {})
    if any(k.startswith(('LD_', 'WINE', 'XDG_')) or k in ('PYTHONPATH','PYTHONHOME','HOME') for k in snapshot['policy'].get('Environment',{})):
        raise r.ReleaseError('native environment changes reserved runtime/state paths; reconcile through native controls')
    shared = set(context.get('shared', '').split(';'))
    devices = set(context.get('devices', '').split(';')) - {''}
    sockets = set(context.get('sockets', '').split(';')) - {''}
    if 'ipc' in shared or 'shm' in devices or not devices <= ({'all'} if all_devices(capabilities) else set()):
        raise r.ReleaseError('native device/shared-memory policy violates the requested v1 boundary')
    if ('network' in shared) != bool(grants(capabilities, 'network')):
        raise r.ReleaseError('effective native network permission differs; change it through Flatseal/native CLI')
    if not sockets <= ({'x11', 'fallback-x11'} if grants(capabilities, 'display') else set()):
        raise r.ReleaseError('native socket grant exceeds the supported v1 combination')
    if all_devices(capabilities) and 'all' not in devices:
        raise r.ReleaseError('required native All Devices permission is absent')
    if grants(capabilities, 'display') and not sockets & {'x11','fallback-x11'}:
        raise r.ReleaseError('required native X11 permission is absent')
    if context.get('features', '').strip(';'):
        raise r.ReleaseError('native feature extensions require separate qualification')
    # Independent folder grants are native authority, but cannot expose policy,
    # recovery or another application's private state.
    for token in native_filesystems(snapshot):
        if token.startswith('!'): continue
        path = _native_path(token)
        if path is None or any(overlaps(path, p) for p in protected_paths(capabilities['applicationId'], root)):
            raise r.ReleaseError('native folder grant exposes protected/unsupported scope; review native permissions')
        if path.absolute()!=path.resolve():raise r.ReleaseError('native folder alias requires an explicit canonical binding before v1 launch')
        if path.is_dir():
            info=path.stat()
            snapshot.setdefault('mountIdentities',[]).append({'path':str(path),'device':info.st_dev,'inode':info.st_ino})
    for entry in paths:
        access = path_access(snapshot, entry['host'])
        if not entry['intentGranted'] and overlapping_native_grants(snapshot,entry['host']):
            raise r.ReleaseError('native permission union defeats a folder denial')
        if entry['granted'] and access != entry['access']:
            raise r.ReleaseError('effective native folder permission differs; use permissions bind/native controls')
        if entry['granted'] and entry['access']=='read-only' and any(not token.endswith(':ro') for token in overlapping_native_grants(snapshot,entry['host'])):
            raise r.ReleaseError('native writable descendant/parent defeats a read-only folder scope')
    for section in ('Session Bus Policy', 'System Bus Policy'):
        policy = snapshot['policy'].get(section, {})
        if any(value in ('talk', 'own') and not name.startswith('org.freedesktop.portal.') for name,value in policy.items()):
            raise r.ReleaseError('native bus extension requires separate qualification')
    return snapshot


def prepare(release, root, *, accepted=None, create=False):
    entry = release['entry'];plan = entry['plan'];app = plan['desktop']['id'];kind = entry['format']
    if platform.machine() != 'x86_64' or entry['architecture'] != 'x86_64':
        raise r.ReleaseError('managed v1 launch currently targets native Linux x86_64; this host cannot qualify it')
    os_release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            name,value=line.split('=',1);os_release[name]=value.strip('"')
    if os_release.get('ID')!='ubuntu' or os_release.get('VERSION_ID')!='24.04':
        raise r.ReleaseError('managed v1 initially qualifies Ubuntu 24.04; this OS requires separate native qualification')
    apparmor=Path('/sys/module/apparmor/parameters/enabled')
    if not apparmor.is_file() or apparmor.read_text().strip()!='Y':
        raise r.ReleaseError('qualified v1 tuple requires AppArmor enabled and scoped namespace authorization')
    if os.getuid()==0:raise r.ReleaseError('managed v1 runs as a regular desktop user')
    local = local_bindings(app,kind)
    if local.get('conflicted'):raise r.ReleaseError('conflicted native binding receipt; rerun bind after reconciliation')
    capabilities = compile_capabilities(plan['recipe'],kind,**applicable_inputs(plan['recipe'],local))
    require_supported(capabilities)
    if accepted != capabilities['contractDigest'] and local.get('acceptedContractDigest') != capabilities['contractDigest']:
        raise r.ReleaseError('permissions require explicit acceptance of contract ' + capabilities['contractDigest'] + '; inspect the release plan first')
    paths = resolve_files(capabilities,app,root,create=False)
    display = x11() if grants(capabilities,'display') else None
    snapshot = native_policy(release,capabilities,paths,root) if kind=='flatpak' else None
    # Denied native grants and missing display/sandbox prerequisites cannot
    # cause Cage to create a host folder as a side effect of failed preflight.
    if create:paths=resolve_files(capabilities,app,root,create=True)
    policy = {'capabilities':capabilities,'paths':paths,'display':display,
              'native':snapshot,'baseline':'cage.local-desktop/v1'}
    policy['digest'] = snapshot['digest'] if snapshot else digest(policy)
    return policy
