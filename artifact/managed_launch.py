"""Trusted v1 import and launch adapters. Artifact code runs only after confinement."""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from artifact import releases as r
from artifact import capability_runtime as policy
from runtime.appimage_runtime import materialize, MATERIALIZER_ABI, interpreter_slot, INTERPRETER_PLACEHOLDER
from runtime.desktop_launch import inventory_tree, verify_inventory, digest_json

BLOCKED_SYSCALLS = ('ptrace','process_vm_readv','process_vm_writev','mount','umount2','pivot_root','setns','unshare',
                   'open_by_handle_at','name_to_handle_at','bpf','perf_event_open','keyctl','add_key','request_key',
                   'init_module','finit_module','delete_module','kexec_load','kexec_file_load','reboot','swapon','swapoff',
                   'iopl','ioperm','userfaultfd')


def oci_seccomp():
    return {'defaultAction':'SCMP_ACT_ALLOW','architectures':['SCMP_ARCH_X86_64','SCMP_ARCH_X86','SCMP_ARCH_X32'],
            'syscalls':[{'names':list(BLOCKED_SYSCALLS),'action':'SCMP_ACT_ERRNO','errnoRet':1}]}


def state_root(record, release):
    app = release['manifest']['application']['id'];kind = release['entry']['format']
    data = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
    if kind == 'flatpak':return Path.home()/'.var/app'/app/'data'/app
    if kind == 'appimage':return data/'cage/appimage'/app
    return Path(record['stateDirectory'])/app


def _tool(name):
    path = shutil.which(name)
    if not path:raise r.ReleaseError('missing sandbox prerequisite: ' + name)
    return path


def squash_offset(package):
    """Locate a bounded type-2 SquashFS superblock, without invoking the artifact."""
    package = Path(package)
    with package.open('rb') as handle:
        header = handle.read(min(package.stat().st_size,64*1024**2))
    if header[:4] != b'\x7fELF' or header[8:11] != b'AI\x02':
        raise r.ReleaseError('managed import requires a type-2 ELF AppImage')
    offsets=[];start=0
    while (offset:=header.find(b'hsqs',start)) >= 0:
        start=offset+4
        if len(header)-offset < 96:continue
        block=header[offset:offset+96]
        compression=struct.unpack_from('<H',block,20)[0]
        major,minor=struct.unpack_from('<HH',block,28)
        used=struct.unpack_from('<Q',block,40)[0]
        if major==4 and minor==0 and compression in range(1,7) and 96 < used <= package.stat().st_size-offset:
            offsets.append(offset)
    if len(offsets)!=1:raise r.ReleaseError('missing or ambiguous AppImage SquashFS identity')
    return offsets[0]


def import_appimage(release, folder):
    """Use patched host SquashFS tools; never AppRun, --appimage-extract or FUSE."""
    entry=release['entry'];app=entry['plan']['desktop']['id'];source=Path(release['directory'])/entry['package']['name']
    if r.hash_file(r.regular(source)) != entry['package']['sha256']:raise r.ReleaseError('AppImage package changed')
    destination=Path(folder)/'imports'/release['digest'];ready=destination/'inventory.json';appdir=destination/'app'
    if ready.exists():
        verify_inventory(appdir,r.parse(r.small(ready,64*1024**2)))
        return appdir
    if destination.exists():raise r.ReleaseError('interrupted AppImage import retained; move it aside before retrying')
    extractor=_tool('unsquashfs')
    version=subprocess.run([extractor,'-version'],capture_output=True,text=True,check=False)
    match=re.search(r'unsquashfs version (\d+)\.(\d+)(?:\.(\d+))?',version.stdout+version.stderr)
    if version.returncode not in (0,1) or not match or tuple(int(v or 0) for v in match.groups()) < (4,6,1):
        raise r.ReleaseError('trusted extraction requires host squashfs-tools >= 4.6.1')
    offset=squash_offset(source)
    destination.mkdir(parents=True,mode=0o700)
    # Extraction is unprivileged and xattrs/set-ID ownership are never adopted.
    subprocess.run([extractor,'-no-progress','-no-xattrs','-processors','1','-o',str(offset),'-d',str(appdir),str(source)],
                   check=True,capture_output=True,text=True)
    inventory=inventory_tree(appdir)
    metadata=appdir/'usr/share/cage'/app
    if r.parse(r.small(metadata/'desktop.json')) != entry['plan']:raise r.ReleaseError('imported AppImage plan differs from signed release')
    if digest_json(r.parse(r.small(metadata/'manifest.cage.json'))) != entry['recipeDigest']:
        raise r.ReleaseError('imported recipe differs from signed release')
    closure=r.parse(r.small(metadata/'native-dependencies.json'))
    private=r.parse(r.small(appdir/'usr/libexec/private-runtime.json'))
    if (private != closure['privateRuntime'] or digest_json({'privateRuntime':private,'libraries':closure['libraries']}) != entry['plan']['runtimeClosureDigest']):
        raise r.ReleaseError('private runtime closure identity differs')
    verify_inventory(appdir/'usr/lib/cage-native',closure['libraries'])
    _write(ready,inventory)
    return appdir


def _write(path, value):
    from runtime.desktop_launch import _write_state_record
    _write_state_record(path,value)


def verify_transform(source, prepared, manifest):
    """Check that only the reserved PT_INTERP bytes changed in each native ELF."""
    for item in manifest['files']:
        relative=Path(item['path']);before=Path(source)/relative;after=Path(prepared)/relative
        raw=bytearray(after.read_bytes())
        if item['interpreter']:
            slot=interpreter_slot(before)
            if not slot:raise r.ReleaseError('missing reserved interpreter')
            start,size=slot
            expected=os.fsencode(Path('/app')/manifest['loader'])+b'\0'
            if bytes(raw[start:start+size]) != expected.ljust(size,b'\0'):
                raise r.ReleaseError('unpermitted private interpreter transformation')
            raw[start:start+size]=os.fsencode(INTERPRETER_PLACEHOLDER)+b'\0'
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise r.ReleaseError('prepared ELF changed outside its permitted interpreter slot')


def seccomp_fd():
    """Host-generated syscall filter passed to Bubblewrap, never artifact BPF."""
    library=ctypes.util.find_library('seccomp')
    if not library:raise r.ReleaseError('host libseccomp unavailable')
    lib=ctypes.CDLL(library,use_errno=True)
    lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
    lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    lib.seccomp_export_bpf.argtypes=[ctypes.c_void_p,ctypes.c_int]
    lib.seccomp_release.argtypes=[ctypes.c_void_p]
    context=lib.seccomp_init(0x7fff0000)
    if not context:raise r.ReleaseError('cannot initialize syscall baseline')
    output=tempfile.TemporaryFile()
    try:
        for name in BLOCKED_SYSCALLS:
            number=lib.seccomp_syscall_resolve_name(name.encode())
            if number>=0 and lib.seccomp_rule_add(context,0x50001,number,0)!=0:raise r.ReleaseError('cannot build syscall baseline')
        if lib.seccomp_export_bpf(context,output.fileno())!=0:raise r.ReleaseError('cannot export syscall baseline')
        output.seek(0)
        return output
    except BaseException:
        output.close();raise
    finally:lib.seccomp_release(context)


def environment(release, effective):
    app=release['manifest']['application']['id']
    return {'CAGE_MANAGED_V1':'1','CAGE_POLICY_DIGEST':effective['digest'],
            'CAGE_WINE_DRIVES':json.dumps({x['wineDrive']:x['host'] for x in effective['paths'] if x['granted'] and x['wineDrive']},sort_keys=True),
            'CAGE_EXPECTED_FILES':json.dumps([{'path':x['host'],'device':x['device'],'inode':x['inode']} for x in effective['paths'] if x['granted'] and 'inode' in x]
                                           +(effective.get('native') or {}).get('mountIdentities',[]),sort_keys=True),
            'CAGE_EXPECTED_FLATPAK_COMMIT':release['entry'].get('flatpakCommit','')}


def bubblewrap_args(release, appdir, prepared, root, effective, filter_fd, files=(), action=None):
    plan=release['entry']['plan'];app=plan['desktop']['id'];home=Path.home();data=Path(os.environ.get('XDG_DATA_HOME',home/'.local/share'))
    args=[_tool('bwrap'),'--die-with-parent','--new-session','--unshare-user','--unshare-pid','--unshare-ipc','--unshare-uts',
          '--cap-drop','ALL','--clearenv','--proc','/proc','--tmpfs','/tmp','--tmpfs','/run',
          '--dir',str(home),'--dir',str(data),'--ro-bind',str(appdir),'/app','--ro-bind',str(prepared),'/run/cage/native',
          '--bind',str(root),str(data/'cage/appimage'/app),'--seccomp',str(filter_fd),'--chdir',str(home)]
    if not policy.grants(effective['capabilities'],'network'):args+=['--unshare-net']
    if policy.all_devices(effective['capabilities']):
        args+=['--dev-bind','/dev','/dev','--tmpfs','/dev/shm']
        for source in ('/sys','/run/udev'):
            if not Path(source).is_dir():raise r.ReleaseError('required live device enumeration metadata unavailable: '+source)
            args+=['--ro-bind',source,source]
    else:args+=['--dev','/dev']
    for source in ('/etc/resolv.conf','/etc/hosts','/etc/nsswitch.conf','/etc/ssl/certs','/etc/localtime'):
        if Path(source).exists():args+=['--ro-bind',source,source]
    # No host passwd/group/NSS modules, bus sockets, home, Cage ledger or caches.
    for entry in effective['paths']:
        if entry['granted']:args += ['--ro-bind' if entry['access']=='read-only' else '--bind',entry['host'],entry['host']]
    env={'HOME':str(home),'XDG_DATA_HOME':str(data),'XDG_CONFIG_HOME':str(root/'home/config'),
         'XDG_CACHE_HOME':str(root/'home/cache'),'PATH':'/run/cage/native/usr/wine/bin',
         'USER':os.environ.get('USER','cage'),'LANG':os.environ.get('LANG','C.UTF-8'),
         'LC_CTYPE':'C.UTF-8','LOCPATH':'/run/cage/native/usr/lib/cage-native/locale',**environment(release,effective)}
    if effective['display']:
        display=effective['display'];args+=['--ro-bind',display['socket'],display['socket'],'--ro-bind',display['authority'],'/run/cage/Xauthority']
        env.update(DISPLAY=display['display'],XAUTHORITY='/run/cage/Xauthority')
    for name,value in env.items():args+=['--setenv',name,value]
    args+=['/run/cage/native/usr/python/bin/python3','-I','/app/usr/libexec/desktop_launch.py','/app/usr/share/cage/'+app+'/desktop.json']
    if action:args+=['--cage-'+action]
    return args+['--',*map(str,files)]


def container_args(record, release, effective, files=(), action=None, *, seccomp_profile=None):
    if seccomp_profile is None:raise r.ReleaseError('host-generated OCI syscall profile required')
    engine=_tool('podman')
    info=json.loads(r.command([engine,'--remote=false','info','--format=json'],capture_output=True,text=True).stdout)
    if not info.get('host',{}).get('security',{}).get('rootless') or info['host'].get('ociRuntime',{}).get('name')!='crun':
        raise r.ReleaseError('v1 OCI requires local rootless Podman/crun')
    if os.environ.get('CONTAINER_HOST') or os.environ.get('CONTAINER_CONNECTION'):
        raise r.ReleaseError('remote container resources remain unsupported')
    state=Path(record['stateDirectory']);(state/'home').mkdir(parents=True,exist_ok=True)
    args=[engine,'--remote=false','run','--rm','--pull=never','--userns=keep-id','--user',f'{os.getuid()}:{os.getgid()}',
          '--group-add=keep-groups','--cap-drop=ALL','--security-opt=no-new-privileges','--read-only',
          '--security-opt=seccomp='+str(seccomp_profile),
          '--ipc=private','--pid=private','--uts=private','--network='+('host' if policy.grants(effective['capabilities'],'network') else 'none'),
          '--tmpfs=/tmp:rw,nosuid,nodev','--tmpfs=/run:rw,nosuid,nodev','--tmpfs=/var/tmp:rw,nosuid,nodev',
          '--mount=type=bind,source='+str(state)+',destination=/var/lib/cage/state',
          '-e','PUID='+str(os.getuid()),'-e','PGID='+str(os.getgid()),'-e','CAGE_SESSION_MODE=desktop']
    if policy.all_devices(effective['capabilities']):
        args+=['--mount=type=bind,source=/dev,destination=/dev','--tmpfs=/dev/shm:rw,nosuid,nodev,notmpcopyup']
        if not Path('/run/udev').is_dir():raise r.ReleaseError('required host udev enumeration metadata unavailable')
        args+=['--mount=type=bind,source=/run/udev,destination=/run/udev,ro=true']
    for entry in effective['paths']:
        if entry['granted']:
            if any(c in entry['host'] for c in (',',':')):raise r.ReleaseError('container mount path cannot safely represent delimiters')
            args+=['--mount=type=bind,source='+entry['host']+',destination='+entry['host']+(',ro=true' if entry['access']=='read-only' else '')]
    env=environment(release,effective)
    if effective['display']:
        display=effective['display'];args+=['--mount=type=bind,source='+display['socket']+',destination='+display['socket']+',ro=true',
            '--mount=type=bind,source='+display['authority']+',destination=/tmp/cage-xauthority,ro=true']
        env.update(DISPLAY=display['display'],XAUTHORITY='/tmp/cage-xauthority')
    for name,value in env.items():args+=['-e',name+'='+value]
    args+=[release['entry']['imageId']]
    if action:args+=['--cage-'+action]
    return args+['--',*map(str,files)]


def launch(record, release, folder, root, *, files=(), action=None, accepted=None):
    effective=policy.prepare(release,root,accepted=accepted,create=True)
    kind=release['entry']['format'];app=release['manifest']['application']['id']
    for name in files:
        path=Path(name).resolve()
        if not any(x['granted'] and (path==Path(x['host']) or Path(x['host']) in path.parents) for x in effective['paths']):
            raise r.ReleaseError('document is outside approved filesystem grants')
    if kind=='flatpak':
        from artifact.updates import _ref
        from runtime import capability_guard
        env=environment(release,effective)
        # The native runtime's isolated Python evaluates host Cage's guard
        # before importing any /app code. A publisher cannot replace this guard
        # in its artifact to hide a concurrent Flatseal permission change.
        code=Path(capability_guard.__file__).read_text()+'\ncheck(json.loads('+repr(json.dumps(release['entry']['plan']))+'))\n'
        code+='import runpy, sys\nsys.argv = '+repr(['/app/libexec/cage-desktop-launch.py','/app/share/cage/'+app+'/desktop.json',
                *(['--cage-'+action] if action else []),'--',*map(str,files)])+'\nrunpy.run_path(sys.argv[0], run_name="__main__")\n'
        args=['flatpak','run','--user','--commit='+release['entry']['flatpakCommit'],'--runtime-commit='+release['entry']['plan']['target']['platformCommit'],
              '--command=/usr/bin/python3',*['--env='+k+'='+v for k,v in env.items()],_ref({'plan':release['entry']['plan']}),'-I','-c',code]
        return r.command(args,stdin=subprocess.DEVNULL)
    if kind=='oci':
        with tempfile.TemporaryDirectory(prefix='cage-seccomp-') as directory:
            profile=Path(directory)/'profile.json';profile.write_text(json.dumps(oci_seccomp(),sort_keys=True))
            return r.command(container_args(record,release,effective,files,action,seccomp_profile=profile),stdin=subprocess.DEVNULL)
    appdir=import_appimage(release,folder)
    if release['entry']['plan'].get('materializerABI')!=MATERIALIZER_ABI:raise r.ReleaseError('unsupported materializer ABI')
    private=r.parse(r.small(appdir/'usr/libexec/private-runtime.json'))
    state=state_root(record,release);state.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cage-native-') as temporary, seccomp_fd() as filter_file:
        prepared=Path(temporary)
        materialize(appdir,prepared,private,namespace_root='/app')
        verify_transform(appdir,prepared,private)
        return r.command(bubblewrap_args(release,appdir,prepared,state,effective,filter_file.fileno(),files,action),pass_fds=(filter_file.fileno(),),stdin=subprocess.DEVNULL)
