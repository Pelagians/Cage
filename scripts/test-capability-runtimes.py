#!/usr/bin/env python3
"""Build and execute the real v1 adapters with disposable Wine 11 probe state.

Only local producer candidates are used: this bootstraps runtime evidence without
inventing a prequalified signed release. Production import, preflight, namespace,
native policy guard and prefix lifecycle code are exercised unchanged.
Physical USB protocols, Harmony services and synchronization are not qualified.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact import managed_launch as managed, permissions, releases
from artifact.flatpak import export_flatpak
from artifact.appimage import export_appimage
from artifact.inspection import verify_bundle
from builder.flatpak import run_flatpak
from core.capabilities import compile_capabilities
from core.media import stage_media
from runtime.desktop_launch import _write_state_record, inventory_tree, digest_json, plan_identity, _read_generations


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def windows(path):return 'Z:'+str(path).replace('/','\\')


def command(args,log,timeout=1500):
    print('[runtime parity] '+str(log),flush=True)
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=timeout)
    Path(log).parent.mkdir(parents=True,exist_ok=True)
    Path(log).write_text(result.stdout+'\n'+result.stderr)
    if result.returncode:raise RuntimeError(f'{args[:4]} failed ({result.returncode}); see {log}\n'+result.stderr[-4000:])
    return result.stdout.strip()


class Echo(socketserver.StreamRequestHandler):
    def handle(self):
        if self.rfile.readline(64)==b'cage-parity-ping\n':self.wfile.write(b'cage-parity-pong\n')


class UnixEcho(socketserver.ThreadingUnixStreamServer):pass


@contextmanager
def endpoints(name):
    servers=[socketserver.ThreadingTCPServer(('127.0.0.1',0),Echo),UnixEcho('\0'+name,Echo)]
    threads=[]
    try:
        for server in servers:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();threads.append(thread)
        yield servers[0].server_address[1]
    finally:
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join(timeout=5)


class NullFixture:
    """Only a fresh, owned alias of /dev/null; never a physical device."""
    def __init__(self,token):self.path=Path('/dev')/('cage-parity-'+token);self.inode=None
    def create(self):
        if self.path.exists() or self.path.is_symlink():raise RuntimeError('synthetic device path already occupied; retained')
        subprocess.run(['sudo','-n','mknod','-m','0600',str(self.path),'c','1','3'],check=True)
        subprocess.run(['sudo','-n','chown',f'{os.getuid()}:{os.getgid()}',str(self.path)],check=True)
        info=self.path.lstat();self.inode=info.st_ino;self.verify()
    def verify(self):
        info=self.path.lstat()
        if not stat.S_ISCHR(info.st_mode) or info.st_rdev!=os.makedev(1,3) or info.st_uid!=os.getuid() or info.st_ino!=self.inode:
            raise RuntimeError('synthetic fixture ownership/type changed; retained')
    def remove(self):
        if self.inode is None:return
        self.verify();subprocess.run(['sudo','-n','rm','--',str(self.path)],check=True);self.inode=None


def fixture_recipe(app,workspace,paths):
    archive=workspace/'inputs/probe.zip'
    return {'schemaVersion':'cage.app/v1','id':app,'name':'cage-runtime-parity','version':'1.0.0',
        'runtime':{'provider':'wine','version':'11.0','wineGraphics':'xwayland'},
        'sources':[{'id':'probe','type':'archive','policy':'redistributable','path':'inputs/probe.zip','sha256':releases.hash_file(archive)}],
        'modules':[{'type':'files','mappings':[{'source':'sources/probe/media','target':'C:/CageProbe','mode':'merge'}]}],
        'launch':{'entrypoint':'C:/CageProbe/probe.exe','workingDirectory':'C:/CageProbe',
                  'args':['--runtime-config',windows(paths['read']/'run.conf')]},
        'desktop':{'id':app,'name':'Cage Runtime Parity','summary':'Disposable runtime parity probe','license':'MIT',
                   'homepage':'https://github.com/Pelagians/Cage','categories':['Utility'],'documentsDirectory':'CageParity'},
        'execution':{'environment':'local-desktop','targets':['oci','flatpak','appimage'],'fallbacks':[]},
        'permissions':{'requests':[
            {'id':'read-files','kind':'filesystem','reason':'Read controlled fixtures','required':True,
             'location':{'base':'absolute','path':str(paths['read'])},'access':'read-only'},
            {'id':'write-files','kind':'filesystem','reason':'Write controlled fixtures','required':True,
             'location':{'base':'absolute','path':str(paths['write'])},'access':'read-write','wineDrive':'H'},
            {'id':'window','kind':'display','backend':'x11','reason':'Render the actual probe window','required':True},
            {'id':'network','kind':'network','reason':'Connect controlled host endpoints','required':False},
            {'id':'devices','kind':'device-class','class':'all','hotplug':'required','reason':'Observe synthetic device views','required':False}]}}


def prepare_payload(workspace,probe):
    archive=workspace/'inputs/probe.zip';archive.parent.mkdir(parents=True)
    raw=Path(probe).read_bytes();offset=struct.unpack_from('<I',raw,60)[0]
    if raw[:2]!=b'MZ' or raw[offset:offset+6]!=b'PE\0\0\x64\x86':raise RuntimeError('expected compiled x86_64 Windows probe')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED) as target:
        for name,data in [('probe.exe',raw),('capability_probe.py',(ROOT/'tests/probes/capability_probe.py').read_bytes())]:
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.external_attr=0o100644<<16;target.writestr(info,data)
    stage_media(archive,name='probe',workspace=workspace)
    return releases.hash_file(archive)


def build_candidates(work,store,app,recipe_path,evidence,formats=('oci','flatpak','appimage')):
    fp=None;ai=None
    if set(formats)&{'flatpak','appimage'}:
        command([sys.executable,'-m','cage','build',recipe_path,'--target','flatpak','--workspace',work/'workspace',
                 '--flatpak-store',store,'--output',work/'desktop-bundles'],evidence/'build-desktop.log')
        bundle=work/'desktop-bundles/cage-runtime-parity-1.0.0'
        if 'flatpak' in formats:
            fp=export_flatpak(bundle,output=work/'probe.flatpak',store=store)
            write(evidence/'flatpak-export.json',fp)
        if 'appimage' in formats:
            ai=export_appimage(bundle,output=work/'probe.AppImage',store=store,cache=ROOT/'.cage/appimage-tools')
            write(evidence/'appimage-export.json',ai)
    if 'oci' in formats:
        command(['podman','--remote=false','pull','ghcr.io/pelagians/cage-wine:11.0'],evidence/'oci-pull.log')
        base=json.loads(command(['podman','--remote=false','image','inspect','ghcr.io/pelagians/cage-wine:11.0'],evidence/'oci-base.log'))[0]
        image='ghcr.io/pelagians/cage-wine@'+base['Digest']
        if image not in base['RepoDigests']:raise RuntimeError('inspected platform digest has no Wine repository binding')
        oci_bundle=work/'oci-bundles/cage-runtime-parity-1.0.0'
        try:
            command([sys.executable,'-m','cage','build',recipe_path,'--engine','podman','--workspace',work/'workspace',
                     '--runtime-image',image,'--output',work/'oci-bundles','--build-timeout','900'],evidence/'build-oci.log')
        finally:
            if oci_bundle.is_dir():write(evidence/'oci-bundle-verification.json',verify_bundle(oci_bundle))
        tag='localhost/cage-runtime-parity:'+hashlib.sha256(app.encode()).hexdigest()[:16]
        command([sys.executable,'-m','cage','export','oci',oci_bundle,
                 '--engine','podman','--graphics','desktop','--tag',tag,'--context-dir',work/'oci-export'],evidence/'oci-export.log')
        oci_plan,arch,image_id,recipe_digest=releases.oci_metadata(tag,'podman')
        write(evidence/'oci-plan.json',oci_plan)
    candidates={}
    for kind,result in [('flatpak',fp),('appimage',ai)]:
        if result is None:continue
        entry={'format':kind,'architecture':'x86_64','plan':result['plan'],
               'package':{'name':Path(result['output']).name,'sha256':result['sha256']},'recipeDigest':result['plan']['sourceManifestDigest']}
        if kind=='flatpak':entry['flatpakCommit']=result['commit']
        candidates[kind]={'entry':entry,'directory':str(work),'digest':result['sha256'],
                          'manifest':{'application':{'id':app}}}
    if 'oci' in formats:
        candidates['oci']={'entry':{'format':'oci','architecture':arch,'imageId':image_id,'plan':oci_plan,'recipeDigest':recipe_digest},
                           'directory':str(work),'digest':image_id.split(':')[-1],'manifest':{'application':{'id':app}}}
    assert len({x['entry']['plan']['capabilities']['contractDigest'] for x in candidates.values()})==1
    return candidates


def install_native(release,consumer,evidence):
    target=release['entry']['plan']['target'];runtime=target['platform']+'/'+target['architecture']+'/'+target['branch']
    run_flatpak(['remote-add','--user','--if-not-exists','flathub',target['remoteUrl']],store=consumer)
    run_flatpak(['install','--user','--noninteractive','--assumeyes','--no-related','flathub',runtime],store=consumer)
    run_flatpak(['update','--user','--noninteractive','--assumeyes','--no-related','--commit='+target['platformCommit'],runtime],store=consumer)
    command(['flatpak','install','--user','--noninteractive','--assumeyes','--no-deps','--no-related','--bundle',
             Path(release['directory'])/release['entry']['package']['name']],evidence/'flatpak-install.log')


def configure(app,kind,paths,network,rebound,evidence,*,devices=True):
    active=paths['replacement'] if rebound else paths['write']
    receipt={'schemaVersion':'cage.local-capability-bindings/v1','applicationId':app,
             'decisions':{} if network else {'network':'deny'},
             'bindings':{'write-files':{'base':'absolute','path':str(active)}} if rebound else {}}
    if not network and devices:receipt['decisions']['devices']='deny'
    path=permissions.bindings_path(app,kind);path.parent.mkdir(parents=True,exist_ok=True)
    _write_state_record(path,receipt)
    if kind=='flatpak':
        # Explicit test-operator native edits. Cage launch/bind code never writes
        # overrides. Only this new, disposable application ID is addressed.
        args=['flatpak','override','--user','--share=network' if network else '--unshare=network',
              '--device=all' if network and devices else '--nodevice=all']
        args+=['--nofilesystem='+str(paths['replacement'] if not rebound else paths['write']),
               '--filesystem='+str(active)+':rw']
        command([*args,app],evidence/'native-edit.log')
    return active


def config(app,kind,paths,active,case,port,abstract,device,host_process,shm,evidence,counter,devices_granted):
    output=active/(kind+'-'+case+'-'+str(counter)+'-'+hashlib.sha256(str(evidence).encode()).hexdigest()[:8]);output.mkdir()
    py='/run/cage/native/usr/python/bin/python3' if kind=='appimage' else '/usr/bin/python3'
    seed={'oci':'/opt/cage/bundle/prefix','flatpak':'/app/share/cage/'+app+'/seed',
          'appimage':'/app/usr/share/cage/'+app+'/seed'}[kind]
    package='/opt/cage/bundle' if kind=='oci' else '/app'
    runtime='/run/cage/native' if kind=='appimage' else '/usr'
    linux=output/'linux.json';win=output/'windows.json';ready=output/'ready.json';ack=output/'observed'
    shared=case!='isolated'
    argv=[py,'-I',seed+'/drive_c/CageProbe/capability_probe.py','--read',str(paths['read']/'canary'),'--write',str(active),
          '--denied',str(paths['denied']/'canary'),'--protected',str(paths['protected']/'canary'),
          '--old',str(paths['write']/'canary'),'--package',package,'--runtime',runtime,'--port',str(port),'--abstract',abstract,
          '--device',str(device.path),'--hotplug-seconds','15' if devices_granted else '0','--ready',str(ready),'--output',str(linux),
          '--shm',str(shm),'--host-process-pid',str(host_process.pid),'--host-process-marker','cage-parity-host-control',
          '--wine','/run/cage/native/usr/wine/bin/wine' if kind=='appimage' else 'wine']
    values=['cage-runtime-probe/v1',windows(paths['read']/'canary'),windows(active),windows(paths['denied']/'canary'),
            windows(paths['protected']/'canary'),windows(paths['write']/'canary'),str(port),windows(py),
            subprocess.list2cmdline(argv),windows(linux),windows(win),windows(ack)]
    (paths['read']/'run.conf').write_text('\n'.join(values)+'\n')
    write(evidence/'configuration.json',{'nativeChildArguments':argv,'activeFolder':str(active),'case':case})
    return linux,win,ready,ack


def run_case(release,record,work,paths,case,port,abstract,device,host_process,shm,evidence,counter,*,launch=None,setup=True):
    app=release['manifest']['application']['id'];kind=release['entry']['format'];evidence.mkdir(parents=True)
    print(f'[runtime parity] launch {kind}/{case}',flush=True)
    assert host_process.poll() is None,'host process control exited'
    assert b'cage-parity-host-control' in Path(f'/proc/{host_process.pid}/cmdline').read_bytes()
    assert shm.read_bytes()==b'cage-probe-canary\n','host shared-memory control unavailable'
    if setup:
        has_devices=any(r['id']=='devices' for r in release['entry']['plan']['recipe']['permissions']['requests'])
        active=configure(app,kind,paths,case!='isolated',case=='rebound',evidence,devices=has_devices)
    else:
        active=paths['replacement'] if case=='rebound' else paths['write']
    if kind=='flatpak':write(evidence/'native-policy.json',permissions.native_snapshot(release))
    effective=compile_capabilities(release['entry']['plan']['recipe'],kind,
        **permissions.applicable_inputs(release['entry']['plan']['recipe'],permissions.local_bindings(app,kind)))
    devices_granted=any(x['grant'] and x['grant']['kind']=='device-class' for x in effective['requests'])
    linux_path,win_path,ready,ack=config(app,kind,paths,active,case,port,abstract,device,host_process,shm,evidence,counter,devices_granted)
    observer={'window':False,'transition':False};errors=[];stop=threading.Event()
    def observe():
        try:
            deadline=time.monotonic()+150
            while not ready.exists():
                if stop.wait(.1):raise RuntimeError('application exited before native child became ready')
                if time.monotonic()>deadline:raise RuntimeError('native child readiness timed out')
            initial=json.loads(ready.read_text())['initialDeviceAccessible']
            if initial != devices_granted:raise AssertionError('initial device view differs from request')
            observer['window']=subprocess.run(['xdotool','search','--onlyvisible','--name','^Cage Runtime Parity$'],capture_output=True).returncode==0
            if devices_granted:
                device.remove();time.sleep(.7);device.create();observer['transition']=True
        except BaseException as exc:errors.append(str(exc))
        finally:ack.write_text('observed\n')
    thread=threading.Thread(target=observe,daemon=True);thread.start()
    try:
        # Exact real exporter outputs; no mock policies, substituted runtime,
        # unsandboxed application path or prequalified signature is involved.
        with (evidence/'launch.log').open('w') as output:
            saved=releases.command;commands=[]
            def captured(args,**kwargs):
                commands.append(list(map(str,args)));write(evidence/'commands.json',commands)
                for argument in args:
                    if str(argument).startswith('--security-opt=seccomp='):
                        shutil.copyfile(str(argument).split('=',2)[2],evidence/'seccomp.json')
                # Capture child output while retaining command/preflight behavior.
                if kwargs.get('capture_output'):return saved(args,**kwargs)
                return saved(args,stdout=output,stderr=subprocess.STDOUT,timeout=240,**kwargs)
            releases.command=captured
            try:
                if launch is None:managed.launch(record,release,work/'managed-imports',work/'trusted-cache',accepted=release['entry']['plan']['capabilities']['contractDigest'])
                else:launch(evidence/'installed-launch.log')
            finally:releases.command=saved
    finally:
        stop.set();thread.join(timeout=10)
        # Retain child failures even when launch or readiness fails before the
        # normal assertions. Wine can close a Unix child's diagnostic streams.
        for source,name in ((linux_path,'linux.json'),(win_path,'windows.json')):
            if source.is_file():shutil.copyfile(source,evidence/name)
    if thread.is_alive() or errors:raise AssertionError('host observer: '+str(errors))
    linux=json.loads(linux_path.read_text());win=json.loads(win_path.read_text())
    write(evidence/'linux.json',linux);write(evidence/'windows.json',win)
    assert linux['status']=='observed',linux
    shared=case!='isolated';rebound=case=='rebound'
    expected_fs={'read':True,'readScopeMutation':False,'write':True,'siblingRead':False,'protectedRead':False,'previousRead':not rebound}
    for name,expected in expected_fs.items():
        assert linux['filesystem'][name] is expected,(kind,case,'linux',name,linux)
        assert win['filesystem'][name] is expected,(kind,case,'windows',name,win)
    assert linux['filesystem']['packageMutation'] is False and linux['filesystem']['runtimeMutation'] is False
    assert all(linux['mounts'].values()),linux['mounts']
    for name in ('noNewPrivileges','zeroCapabilities','seccomp'):assert linux['baseline'][name] is True
    assert linux['baseline']['hostProcessVisible'] is False
    assert linux['baseline']['hostSharedMemoryVisible'] is False
    assert linux['runtime']['wine']=='wine-11.0',linux['runtime']
    assert linux['network']['tcp'] is shared and linux['network']['abstract'] is shared
    assert win['network']['tcp'] is shared
    assert linux['devices']['initialAccessible'] is devices_granted
    assert linux['devices']['liveTransitionObserved'] is devices_granted
    assert linux['devices']['reconnectObserved'] is devices_granted
    assert observer['window'] and win['windowCreated'] and win['nativeChildCompleted']
    assert win['wineDriveWrite'] is True
    assert win['settingsPreserved'] is True
    assert win['stateCounter']==counter,(kind,case,win['stateCounter'],counter)
    state_root=managed.state_root(record,release);state=_read_generations(state_root)
    assert state['generations'][0]['identity']==plan_identity(release['entry']['plan'])
    result={'status':'passed','case':case,'stateCounter':counter,'stateRoot':str(state_root),
            'activePrefix':state['active'],'compatibility':plan_identity(release['entry']['plan']),
            'windowObserved':observer['window'],'syntheticDeviceTransition':observer['transition'],
            'settingsPreserved':win['settingsPreserved'],
            'physicalUsbSynchronization':'unqualified'}
    write(evidence/'result.json',result)
    return result,linux,win


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--store',type=Path,required=True)
    parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--format',choices=('oci','flatpak','appimage'))
    parser.add_argument('--installed-releases',action='store_true',help='Also qualify signed installed lifecycle in disposable consumer homes')
    args=parser.parse_args()
    if platform.machine()!='x86_64' or os.getuid()==0:raise RuntimeError('run as a regular user on native Ubuntu x86_64')
    work=args.workspace.resolve();work.mkdir(parents=True,exist_ok=False)
    evidence=args.evidence.resolve();evidence.mkdir(parents=True,exist_ok=True)
    token=os.environ.get('GITHUB_RUN_ID',str(os.getpid()))+'a'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
    app='io.github.Pelagians.Cage.ParityRun'+token+(args.format or '')
    if (Path.home()/'.var/app'/app).exists():raise RuntimeError('pre-existing native application data retained; choose a fresh run')
    for name in ('data','config','cache','runtime'):
        directory=work/('xdg-'+name);directory.mkdir(mode=0o700);os.environ['XDG_'+name.upper()+'_HOME' if name!='runtime' else 'XDG_RUNTIME_DIR']=str(directory)
    config_path=work/'containers.conf';config_path.write_text('[engine]\ncgroup_manager="cgroupfs"\nevents_logger="file"\nruntime="crun"\n')
    os.environ['CONTAINERS_CONF']=str(config_path)
    consumer=work/'consumer';os.environ['FLATPAK_USER_DIR']=str(consumer)
    workspace=work/'workspace';workspace.mkdir()
    paths={name:work/'fixtures'/(name+' café') for name in ('read','write','replacement','denied')}
    paths['protected']=work/'trusted-cache'
    for path in paths.values():path.mkdir(parents=True);(path/'canary').write_bytes(b'cage-probe-canary\n')
    source_sha=prepare_payload(workspace,args.probe)
    recipe=fixture_recipe(app,workspace,paths)
    if args.installed_releases:
        # Hardware cases stay blocked; never sign synthetic null-device views
        # as the required controlled Windows device/hotplug evidence.
        recipe['permissions']['requests']=[r for r in recipe['permissions']['requests'] if r['id']!='devices']
    recipe_path=workspace/'recipe.json';write(recipe_path,recipe)
    shutil.copyfile(recipe_path,evidence/'recipe.json')
    null=NullFixture(token);null.create()
    shm=Path('/dev/shm')/('cage-parity-'+token)
    with shm.open('xb') as output:output.write(b'cage-probe-canary\n')
    host_process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(2400)','cage-parity-host-control'])
    result={'schemaVersion':'cage.runtime-parity-suite/v1','status':'running','applicationId':app,'sourceArchiveSha256':source_sha,
            'testedCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'formats':{},'physicalUsbSynchronization':'unqualified','myHarmonyWorkflow':'not-qualified-by-probe-suite'}
    try:
        from importlib.util import spec_from_file_location,module_from_spec
        spec=spec_from_file_location('parity_linux_control',ROOT/'tests/probes/capability_probe.py');probe=module_from_spec(spec);spec.loader.exec_module(probe)
        with endpoints('cage-parity-'+token) as port:
            controls={'read':probe.readable(paths['read']/'canary'),'write':probe.writable(paths['write']),
                      'siblingRead':probe.readable(paths['denied']/'canary'),'protectedRead':probe.readable(paths['protected']/'canary'),
                      'tcp':probe.connect(('127.0.0.1',port)),'abstract':probe.connect('\0cage-parity-'+token,socket.AF_UNIX),
                      'deviceAccessible':probe.safe_device(null.path),'dedicatedRecoverableHardware':False}
            assert all(value for key,value in controls.items() if key!='dedicatedRecoverableHardware'),controls
            write(evidence/'host.json',{'controls':controls,'host':{'architecture':platform.machine(),'kernel':platform.release()}})
            formats=(args.format,) if args.format else ('oci','flatpak','appimage')
            candidates=build_candidates(work,args.store.resolve(),app,recipe_path,evidence,formats)
            if 'flatpak' in candidates:install_native(candidates['flatpak'],consumer,evidence)
            for kind in formats:
                release=candidates[kind];record={'stateDirectory':str(work/'oci-state')};folder=evidence/kind
                summary=[];snapshot=None;state_record=None
                try:
                    for counter,case in enumerate(('shared-all','isolated','rebound'),1):
                        case_result,linux,win=run_case(release,record,work,paths,case,port,'cage-parity-'+token,null,host_process,shm,folder/case,counter)
                        summary.append(case_result)
                        state_root=managed.state_root(record,release)
                        if counter==1:
                            state_record=(state_root/'state.json').read_bytes()
                            recovery=state_root/'retained-recovery-fixture'
                            shutil.copytree(state_root/_read_generations(state_root)['active'],recovery,symlinks=True)
                            snapshot=digest_json(inventory_tree(recovery,state_snapshot=True))
                            write(folder/'recovery-inventory.json',inventory_tree(recovery,state_snapshot=True))
                            write(evidence/(kind+'.linux.json'),linux);write(evidence/(kind+'.windows.json'),win)
                        else:
                            assert (state_root/'state.json').read_bytes()==state_record,'permission change selected another generation'
                            assert digest_json(inventory_tree(recovery,state_snapshot=True))==snapshot,'retained recovery copy changed'
                        write(folder/'state.json',json.loads((state_root/'state.json').read_text()))
                    assert len({case['activePrefix'] for case in summary})==1
                    result['formats'][kind]={'status':'passed','cases':summary,'recoveryPreserved':True,
                        'artifactIdentity':release['entry'].get('imageId',release['entry'].get('package',{}).get('sha256')),
                        'contractDigest':release['entry']['plan']['capabilities']['contractDigest']}
                except Exception as exc:
                    # Independent format state permits collecting every adapter's
                    # result in one VM without resetting a failed prefix.
                    result['formats'][kind]={'status':'failed','error':str(exc),'cases':summary}
                finally:write(evidence/'runtime-parity.json',result)
            failures={kind:value['error'] for kind,value in result['formats'].items() if value['status']=='failed'}
            if failures:raise RuntimeError(json.dumps(failures,sort_keys=True))
            if args.installed_releases:
                spec=spec_from_file_location('installed_parity',ROOT/'scripts/test-capability-installed.py')
                installed=module_from_spec(spec);spec.loader.exec_module(installed)
                result['installedReleases']=installed.qualify(sys.modules[__name__],candidates,work,args.store.resolve(),paths,port,
                    'cage-parity-'+token,null,host_process,shm,evidence/'installed')
            result['status']='passed'
    except BaseException as exc:
        result['status']='failed';result['error']=str(exc);raise
    finally:
        write(evidence/'runtime-parity.json',result)
        host_process.terminate();host_process.wait(timeout=10)
        null.remove();shm.unlink()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
