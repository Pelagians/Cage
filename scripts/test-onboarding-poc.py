#!/usr/bin/env python3
"""Shared real GUI proof: legacy adoption, update, save/relaunch and rollback.

Only fresh private state is used. Application-specific actions live in the small
workflow drivers; format adapters share the same lifecycle assertions.
"""
from pathlib import Path
from contextlib import contextmanager
import argparse
import fcntl
import functools
import http.server
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.desktop_launch import inventory_tree, _read_generations, _generation, lifecycle_lock
from application_workflows import WORKFLOWS, share_test_windows
spec = importlib.util.spec_from_file_location('gui', ROOT / 'scripts/test-flatpak-poc.py')
gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f, 'sha256').hexdigest()


def proof_container_processes(container_state):
    """Resolve host PIDs only after matching this proof's private state mount."""
    matched = []; pids = []
    containers = subprocess.check_output(
        ['podman', 'ps', '--all', '--filter', 'volume=/var/lib/cage/state', '--format', '{{.ID}}'],
        text=True, timeout=10).splitlines()
    for container in containers:
        details = json.loads(subprocess.check_output(['podman', 'inspect', container], text=True, timeout=10))[0]
        if not any(mount.get('Source') == str(container_state) and mount.get('Destination') == '/var/lib/cage/state'
                   for mount in details.get('Mounts', [])):continue
        state = details.get('State', {})
        matched.append({'id': container, 'state': state})
        for key in ('Pid', 'ConmonPid'):
            pid = state.get(key)
            if isinstance(pid, int) and pid > 0:pids.append(pid)
        if state.get('Running', True):
            output = subprocess.check_output(['podman', 'top', container, 'hpid'], text=True, timeout=10)
            pids.extend(int(pid.strip()) for pid in output.splitlines() if pid.strip().isdigit())
    return matched, sorted(set(pids))


@contextmanager
def shutdown_trace(destination, executable, container_state):
    """Opt-in CI observer: attach after save, detach before failure diagnostics.

    Trace the owned Wine processes, not the Podman client (which proxies signals).
    No runtime image, application environment or exit status is changed.
    """
    if os.environ.get('CAGE_TEST_TRACE_SHUTDOWN') != '1':
        yield
        return
    if os.environ.get('GITHUB_ACTIONS') != 'true' or container_state is None or not shutil.which('strace'):
        raise RuntimeError('shutdown tracing requires CI, strace and a private container state mount')
    containers, pids = proof_container_processes(container_state)
    targets = []; names = set(); owned = []
    for pid in pids:
        try:
            root = Path('/proc') / str(pid)
            name = (root / 'comm').read_text().strip().casefold()
            status = (root / 'status').read_text()
        except OSError:continue
        # strace prefixes use host PIDs, but kill()/tgkill() arguments use the
        # traced container's PID namespace. Retain both to identify the victim.
        namespace_pids = next((list(map(int, line.split()[1:])) for line in status.splitlines()
                               if line.startswith('NSpid:')), [])
        owned.append({'hostPid': pid, 'comm': name, 'namespacePids': namespace_pids})
        if name in {Path(executable).name[:15].casefold(), 'wineserver', 'wineserver64'}:
            targets.append(pid); names.add(name)
    if (len(containers) != 1 or Path(executable).name[:15].casefold() not in names
            or not names.intersection({'wineserver', 'wineserver64'})):
        raise RuntimeError('cannot identify this proof application and Wine server for shutdown tracing')
    destination.with_suffix('.json').write_text(json.dumps(
        {'container': containers[0]['id'], 'targets': targets, 'processes': owned}, indent=2) + '\n')
    with destination.with_name(destination.name + '-attach.log').open('w') as output:
        trace = subprocess.Popen(['sudo', '-n', 'strace', '-f', '-ttt', '-e', 'trace=%process,%signal',
                                  '-o', str(destination.with_suffix('.log')),
                                  *[arg for pid in targets for arg in ('-p', str(pid))]],
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            def attached():
                if trace.poll() is not None:raise RuntimeError('shutdown tracer exited before attachment')
                for pid in targets:
                    status = (Path('/proc') / str(pid) / 'status').read_text()
                    if '\nTracerPid:\t0\n' in '\n' + status:return False
                return True
            gui.wait_for(attached, 'shutdown tracer attached to private Wine processes', seconds=10)
            yield
        finally:
            # The new process group contains only sudo/strace. Attached Wine
            # processes retain their own groups; SIGINT detaches the observer.
            if trace.poll() is None:
                result = subprocess.run(['sudo', '-n', 'kill', '-INT', '--', '-' + str(trace.pid)],
                                        capture_output=True, timeout=10)
                if result.returncode and trace.poll() is None:
                    raise RuntimeError('could not detach the private shutdown tracer')
                trace.wait(timeout=10)


def shutdown_diagnostics(process, destination, executable, *, container_state=None, kernel=False):
    """Inspect this failed proof, including reparented processes in its container."""
    if kernel and os.environ.get('GITHUB_ACTIONS') == 'true':
        try:
            result = subprocess.run(['sudo', '-n', 'dmesg', '--color=never', '--ctime'],
                                    capture_output=True, text=True, timeout=10, check=False)
            destination.with_name(destination.name + '-kernel.log').write_text((result.stdout + result.stderr)[-256 * 1024:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            destination.with_name(destination.name + '-kernel.log').write_text(str(exc))
        memory = {}
        for name in ('memory.events', 'memory.current', 'memory.peak'):
            try:memory[name] = (Path('/sys/fs/cgroup') / name).read_text()[:4096]
            except OSError as exc:memory[name] = str(exc)
        destination.with_name(destination.name + '-memory.json').write_text(json.dumps(memory, indent=2) + '\n')
    pending = [process.pid]; seen = set(); records = []; matched_containers = []
    if container_state is not None:
        # Rootless conmon/Wine need not remain descendants of the release CLI.
        # Match the unique private proof mount, then verify the mount explicitly.
        try:
            matched_containers, pids = proof_container_processes(container_state)
            pending.extend(pids)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            destination.with_name(destination.name + '-container-error.log').write_text(str(exc))
        destination.with_name(destination.name + '-containers.json').write_text(json.dumps(matched_containers, indent=2) + '\n')
    while pending and len(seen) < 128:
        pid = pending.pop()
        if pid in seen:continue
        seen.add(pid); root = Path('/proc') / str(pid)
        record = {'pid': pid}
        for name in ('comm', 'status', 'wchan', 'syscall', 'maps', 'cmdline'):
            try:record[name] = (root / name).read_text()[:(1024 if name == 'maps' else 128) * 1024]
            except OSError as exc:record[name] = str(exc)
        threads = []
        try:
            for thread in list((root / 'task').iterdir())[:256]:
                entry = {'tid': thread.name}
                for name in ('comm', 'wchan', 'syscall', 'stack'):
                    try:entry[name] = (thread / name).read_text()[:4096]
                    except OSError as exc:entry[name] = str(exc)
                threads.append(entry)
                try:pending.extend(map(int, (thread / 'children').read_text().split()))
                except OSError:pass
        except OSError:pass
        record['threads'] = threads; records.append(record)
    destination.with_suffix('.json').write_text(json.dumps(records, indent=2) + '\n')
    # CI-only debugger, no auto-loaded scripts or network symbol fetching.
    # Attaching is diagnostic after failure; it cannot turn the trial into a pass.
    if os.environ.get('GITHUB_ACTIONS') == 'true' and shutil.which('gdb'):
        for record in records:
            application_process = record.get('comm', '').strip().casefold() == Path(executable).name[:15].casefold()
            client_process = (record['pid'] != process.pid and record.get('comm', '').strip() == 'podman'
                              and 'PPid:\t' + str(process.pid) in record.get('status', '').splitlines())
            if not application_process and not client_process:continue
            commands = ['info registers', 'x/256gx $sp', 'thread apply all bt']
            if application_process and '/aarch64-unix/ntdll.so' in record.get('maps', ''):
                # Pinned Wine 11.20: TEB+0x378 holds its 0x330-byte syscall
                # frame (signal_arm64.c). Native unwinding stops at this frame;
                # retain saved Windows registers/SP and bounded stack/lock words.
                # Read only after failure, while attached to this proof's PID.
                commands += ['set $cage_frame = *(unsigned long long*)($x18+0x378)',
                             'x/102gx $cage_frame',
                             'x/512gx *(unsigned long long*)($cage_frame+0xf8)',
                             'x/128gx *(unsigned long long*)($cage_frame+0xe8)',
                             'x/16gx *(unsigned long long*)($cage_frame+0x98)',
                             'x/16gx *(unsigned long long*)($cage_frame+0xa0)',
                             'x/8hx *(unsigned long long*)($cage_frame+0xa8)']
            commands.append('detach')
            with destination.with_name(destination.name + '-' + str(record['pid']) + '.log').open('w') as output:
                try:
                    subprocess.run(['sudo', '-n', 'gdb', '--batch', '--nx', '--nh',
                                    '-iex', 'set auto-load off', '-iex', 'set debuginfod enabled off',
                                    '-iex', 'set sysroot /proc/' + str(record['pid']) + '/root',
                                    '-p', str(record['pid']), '-ex', 'set pagination off',
                                    *[arg for command in commands for arg in ('-ex', command)]],
                                   stdout=output, stderr=subprocess.STDOUT, timeout=30, check=False)
                except (OSError, subprocess.TimeoutExpired) as exc:output.write(str(exc) + '\n')
            # Native unwinding cannot cross Wine's syscall/ARM64EC frames.
            # Ask the already packaged debugger for Windows frames, inside the
            # failed Flatpak's namespaces and prefix. Never inspect another app.
            if application_process and shutil.which('flatpak') and '/app/' in record.get('maps', ''):
                try:
                    values = (Path('/proc') / str(record['pid']) / 'environ').read_bytes().split(b'\0')
                    prefix = next(v.decode() for v in values if v.startswith(b'WINEPREFIX='))
                    command = ['flatpak', 'enter', str(record['pid']), '/usr/bin/env', prefix,
                               'WINEDEBUG=-all', '/app/bin/wine', 'winedbg', '--command']
                    listing = subprocess.run([*command, 'info proc\nquit'], capture_output=True, text=True, timeout=20)
                    import re
                    target = re.search(r'(?mi)^\s*(?:=>)?\s*([0-9a-f]+)\s+.*' + re.escape(Path(executable).stem), listing.stdout)
                    output_path = destination.with_name(destination.name + '-windows.log')
                    with output_path.open('w') as output:
                        output.write(listing.stdout + listing.stderr); output.flush()
                        if target:
                            subprocess.run([*command, 'bt\ninfo threads\ndetach\nquit', str(int(target[1], 16))],
                                           stdout=output, stderr=subprocess.STDOUT, timeout=30)
                except (OSError, StopIteration, subprocess.TimeoutExpired) as exc:
                    destination.with_name(destination.name + '-windows-error.log').write_text(str(exc))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('format', choices=['flatpak', 'appimage', 'container', 'oci'])
    parser.add_argument('baseline'); parser.add_argument('candidate')
    parser.add_argument('--legacy'); parser.add_argument('--application', choices=WORKFLOWS, default='sumatrapdf')
    parser.add_argument('--trusted', action='store_true', help='Drive the same proof through signed release delivery')
    parser.add_argument('--qualification', help='Completed matching application proof to bind in test releases')
    parser.add_argument('--runtime-migration', action='store_true', help='Qualify a same-application-version, explicitly allowed runtime transition')
    parser.add_argument('--rollback-repair', action='store_true', help='Qualify explicit repaired rollback with a new runtime identity')
    parser.add_argument('--baseline-qualification', help='Independent original-package evidence for trusted repair setup')
    args = parser.parse_args(); kind = args.format; workflow = WORKFLOWS[args.application]()
    if args.rollback_repair and (args.legacy or args.runtime_migration):
        parser.error('repaired rollback is a distinct qualification, without legacy adoption or ordinary runtime migration')
    if args.rollback_repair and args.trusted and not args.baseline_qualification:
        parser.error('trusted repair requires independent original-package baseline qualification')
    stress_relaunches = int(os.environ.get('CAGE_TEST_RELAUNCHES', '0'))
    if not 0 <= stress_relaunches <= 25:
        parser.error('CAGE_TEST_RELAUNCHES must be between 0 and 25')
    initial_relaunches = int(os.environ.get('CAGE_TEST_INITIAL_RELAUNCHES', '0'))
    if not 0 <= initial_relaunches <= 25:
        parser.error('CAGE_TEST_INITIAL_RELAUNCHES must be between 0 and 25')
    app = workflow.app_id
    baseline, candidate = (Path(p).resolve() if kind != 'oci' else p for p in (args.baseline, args.candidate))
    legacy = (args.legacy if kind == 'oci' else Path(args.legacy).resolve()) if args.legacy else None
    if args.runtime_migration and legacy:
        parser.error('adopt the historical manager under its original runtime before qualifying a runtime migration')
    def source_identities():
        if kind in ('flatpak','appimage'):
            return {'sourceArtifactHashes':{'baseline':sha(baseline),'candidate':sha(candidate)}}
        if kind=='oci':
            return {'sourceImageIds':{name:subprocess.check_output(['podman','image','inspect','--format','{{.Id}}',image],text=True).strip()
                                      for name,image in (('baseline',baseline),('candidate',candidate))}}
        return {}
    original_sources=source_identities()
    evidence = Path(os.environ['CAGE_TEST_EVIDENCE']).resolve(); evidence.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ); token = 'cage-onboarding-proof-' + uuid.uuid4().hex
    if kind == 'flatpak':
        private = Path.home() / '.var/app' / app / 'data' / token
        state = private / app
        real = shutil.which('flatpak'); tools = evidence / 'tools'; tools.mkdir()
        shim = tools / 'flatpak'
        shim.write_text('#!/usr/bin/env python3\nimport os,sys\nreal=' + repr(real) + '\nprivate=' + repr(str(private)) + '\n'
            'args=sys.argv[1:]\n'
            'if args[:1]==["run"] and all(not a.startswith("--command=") or a=="--command=cage-desktop-launch" for a in args):\n'
            ' positions=[i for i,a in enumerate(args) if a.split("/")[0]==' + repr(app) + ']\n'
            ' if len(positions)==1:\n'
            '  pos=positions[0]; flags=[a for a in args[1:pos] if not a.startswith("--command=")]\n'
            '  args=["run",*flags,"--command=sh",args[pos],"-c",' + repr('export XDG_DATA_HOME="$1"; shift; exec /app/bin/cage-desktop-launch "$@"') + ',"cage-proof",private,*args[pos+1:]]\n'
            'os.execv(real,[real,*args])\n')
        shim.chmod(0o755); env['PATH'] = str(tools) + os.pathsep + env['PATH']
        documents = Path.home() / 'Documents/Cage' / token
    elif kind == 'appimage':
        env['XDG_DATA_HOME'] = str(evidence / 'data')
        state = evidence / 'data/cage/appimage' / app
        documents = evidence / 'documents'
    else:
        state = evidence / 'state' / app; documents = evidence / 'documents'
        if kind == 'oci':state.parent.mkdir(parents=True)
    documents.mkdir(parents=True)
    document = documents / ('Original café' + workflow.extension); workflow.fixture(document)
    expected = document.read_bytes(); original = document; original_hash = sha(original)
    installed = None
    first_package = legacy or baseline
    release_urls={}; server=None; key=None; release_cache=evidence/'trusted-cache';baseline_version=None
    if args.trusted:
        assert not legacy and kind!='container' and args.qualification
        from artifact import releases
        from artifact.release_install import deploy
        key=evidence/'publisher-public.pem'
        key_temp=tempfile.TemporaryDirectory(prefix='cage-release-proof-key-')
        private=Path(key_temp.name)/'publisher-private.pem'
        releases.generate_key(private,key)
        producer=Path(baseline).parent if kind!='oci' else evidence/'producer'
        producer.mkdir(parents=True,exist_ok=True)
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(producer)))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        for sequence,artifact in enumerate((baseline,candidate),1):
            spec_path=producer/(token+'-'+kind+'-'+str(sequence)+'.spec.json')
            output=producer/(token+'-'+kind+'-'+str(sequence)+'.json')
            item={'format':kind,'path':str(artifact) if kind!='oci' else str(producer/('application-'+str(sequence)+'.oci.tar')),
                  'evidence':str(Path(args.baseline_qualification if args.rollback_repair and sequence==1 else args.qualification).resolve())}
            if kind=='oci':item['image']=artifact
            revision=os.environ.get('CAGE_TEST_SOURCE_REVISION') or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
            spec_path.write_text(json.dumps({'sequence':sequence,'sourceRevision':revision,'artifacts':[item]}))
            releases.create_release(spec_path,private,output)
            if sequence==1:baseline_version=releases.parse(output.read_bytes())['application']['version']
            release_urls[str(artifact)]='http://127.0.0.1:'+str(server.server_port)+'/'+output.name
        key_temp.cleanup()  # Private material is never in the served/uploaded tree.
        old_env=dict(os.environ)
        try:
            os.environ.update(env)
            deploy(release_urls[str(baseline)],key,kind,cache=release_cache,
                   state_dir=state.parent if kind=='oci' else None,exports_dir=documents if kind=='oci' else None)
        finally:os.environ.clear();os.environ.update(old_env)
        if kind=='appimage':installed={'installed':str(Path(env['XDG_DATA_HOME'])/'cage/appimages'/app/'application.AppImage')}
    elif kind == 'flatpak':
        subprocess.run(['flatpak', 'install', '--user', '--noninteractive', '--reinstall', '-y', '--no-related', '--no-deps', '--bundle', str(first_package)], env=env, check=True)
    elif kind == 'appimage':
        installed = json.loads(subprocess.check_output([str(first_package), '--cage-install'], env=env, text=True))
        if os.environ.get('CAGE_TEST_SHARE_WINDOWS'):
            # Genuine historical integration used an ordinary package copy.
            # On a local Btrfs proof, ask the kernel to share only equal bytes.
            target = Path(installed['installed'])
            with first_package.open('rb') as a, target.open('r+b') as b:
                data = bytearray(struct.pack('=QQHHI', 0, target.stat().st_size, 1, 0, 0)
                                 + struct.pack('=qQQiI', b.fileno(), 0, 0, 0, 0))
                fcntl.ioctl(a.fileno(), 0xc0189436, data, True)
                assert struct.unpack_from('=i', data, 48)[0] == 0

    def prefix():
        record = _read_generations(state); return state / record['active']

    def wine_file(path):
        name = '/mnt/cage-inputs/0/' + path.name if kind == 'container' else '/exports/' + path.name if kind == 'oci' else str(path)
        return 'Z:' + name.replace('/', '\\')

    def command(package, action=None, previous=None):
        if args.trusted:
            operation=action or 'run'
            return [sys.executable,'-m','cage','release',operation,
                    release_urls[str(package)] if operation in ('update','rollback-repair') else app,
                    '--key',str(key),'--format',kind,'--cache-dir',str(release_cache),str(document)]
        if kind == 'flatpak':
            if action:
                return [sys.executable, '-m', 'cage', action, 'flatpak', str(package), '--previous-package', str(previous),
                        '--cache-dir', str(evidence / 'package-cache'), *(['--state-dir', str(state)] if action == 'migrate' else []), str(document)]
            return ['flatpak', 'run', '--user', app, *([] if package == legacy else ['--']), str(document)]
        if kind == 'appimage':
            return [str(package), *(['--cage-' + action] if action else []),
                    *(['--previous-package', str(previous)] if action == 'migrate' else []), '--', str(document)]
        if kind == 'container':
            return [sys.executable, '-m', 'cage', 'run', str(package), str(document), '--engine', 'podman', '--graphics', 'desktop',
                    '--state-dir', str(state.parent), '--writable-files', '--name', token,
                    *(['--state-action', action] if action else [])]
        return ['podman', 'run', '--rm', '--pull=never', '--name', token, '--userns=keep-id', '--user', '0:0', '--net=none',
                '--hostname', os.uname().nodename, '--security-opt', 'label=disable', '-e', 'PUID=' + str(os.getuid()), '-e', 'PGID=' + str(os.getgid()),
                '-e', 'DISPLAY', '-e', 'XAUTHORITY=/tmp/cage-xauthority', '-v', env['XAUTHORITY'] + ':/tmp/cage-xauthority:ro',
                '-v', '/tmp/.X11-unix:/tmp/.X11-unix:ro', '-v', str(state.parent) + ':/var/lib/cage/state',
                '-v', str(documents) + ':/exports', str(package), *(['--cage-' + action] if action else []),
                *([] if package == legacy else ['--']), '/exports/' + document.name]

    def window():return gui.command('xdotool', 'search', '--onlyvisible', '--name', workflow.window_pattern).splitlines()[-1]

    shared_windows = set()

    processes = []; handles = []; logs = []; sessions = []
    def run(package, label, action=None, previous=None, preference=False, menu=False):
        nonlocal document
        before = _read_generations(state) if args.rollback_repair else None
        arguments = command(package, action, previous)
        if menu and kind in ('appimage', 'flatpak'):
            if kind == 'appimage':
                desktop = Path(env['XDG_DATA_HOME']) / 'applications' / (app + '.CageAppImage.desktop')
            else:
                original_desktop = Path(env['FLATPAK_USER_DIR']) / 'exports/share/applications' / (app + '.desktop')
                desktop = evidence / 'private.desktop'
                desktop.write_text(original_desktop.read_text().replace('Exec=' + real + ' ', 'Exec="' + str(shim) + '" '))
            arguments = ['gio', 'launch', str(desktop), str(document)]
        output = (evidence / (label + '.log')).open('w'); logs.append(output)
        process = subprocess.Popen(arguments, env=env, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT); processes.append(process)
        handle = gui.wait_for(window, label + ' application window', seconds=180)
        handles.append(handle)
        gui.wait_for(lambda: document.name in gui.command('xdotool', 'getwindowname', handle), 'requested document loaded')
        gui.focus_editor(handle)
        if preference:
            workflow.change_preference(gui)
            gui.wait_for(lambda: gui.command('xdotool', 'getactivewindow') == handle,
                         'application focus after preference command')
            gui.focus_editor(handle)
            time.sleep(.5)
        # Unicode input is opened through argv. Keep typed Save As names ASCII:
        # Xvfb's synthetic keyboard cannot reliably deliver accented key events.
        saved = documents / (label + '-saved' + workflow.extension)
        attempts = 0; next_attempt = 0
        def save_dialog():
            nonlocal attempts, next_attempt
            found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Save As$'],
                                   capture_output=True, text=True).stdout.strip()
            if found:return found
            # A newly mapped Wine window can acquire X11 focus before its
            # document handles accelerators. Retry the real action boundedly,
            # never typing into or dismissing an unexpected modal dialog.
            if attempts < 3 and time.monotonic() >= next_attempt:
                if gui.command('xdotool', 'getactivewindow') == handle:
                    gui.focus_editor(handle)
                    time.sleep(.5)
                    workflow.save_keys(gui)
                    attempts += 1
                next_attempt = time.monotonic() + 2
            return False
        dialog = gui.wait_for(save_dialog, 'Save As dialog')
        gui.command('xdotool', 'windowactivate', '--sync', dialog.splitlines()[-1])
        # Wine can expose the top-level dialog before populating its filename
        # edit. Focus its labelled field after initialization, as a user would.
        time.sleep(1)
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+n')
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+a')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '5', wine_file(saved))
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return')
        def saved_contents():
            if not saved.is_file():return False
            try:workflow.validate_saved(saved, expected)
            except (AssertionError, OSError):return False
            return True
        gui.wait_for(saved_contents, 'complete saved host document contents')
        workflow.validate_saved(saved, expected)
        gui.wait_for(lambda: not subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Save As$'], capture_output=True).stdout, 'Save As closed')
        subprocess.run(['scrot', str(evidence / (label + '.png'))], check=True)
        try:
            with shutdown_trace(evidence / (label + '-trace'), workflow.executable,
                                state.parent if kind in ('container', 'oci') else None):
                gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
                code = process.wait(timeout=120)
            if code != 0:
                shutdown_diagnostics(process, evidence / (label + '-nonzero'), workflow.executable,
                                     container_state=state.parent if kind in ('container', 'oci') else None, kernel=True)
            assert code == 0, f'application/launcher exited {code}; retained log'
        except subprocess.TimeoutExpired:
            shutdown_diagnostics(process, evidence / (label + '-shutdown'), workflow.executable,
                                 container_state=state.parent if kind in ('container', 'oci') else None, kernel=True)
            raise
        def idle():
            try:
                with lifecycle_lock(state):return True
            except Exception:return False
        gui.wait_for(idle, 'Wine stopped and state committed', seconds=60)
        gui.wait_for(lambda: not subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', workflow.window_pattern], capture_output=True).stdout, 'GUI closed')
        if kind == 'flatpak':
            gui.wait_for(lambda: app not in subprocess.check_output(['flatpak', 'ps', '--columns=application'],
                         env=env, text=True).splitlines(), 'Flatpak sandbox stopped', seconds=45)
        document = saved
        record = _read_generations(state); active = _generation(record, record['active'])
        session = {'phase': label, 'identity': active['identity'], 'prefix': record['active'], 'savedSha256': sha(saved)}
        if args.rollback_repair:
            session.update(operation=action or 'run', exitCode=code, wineStopped=True)
            if action=='rollback-repair':
                session['rollbackRepair']=active['rollbackRepair']
                session['repairSourceRole']='previous' if active['rollbackRepair']['source']==before.get('previous') else 'active'
        sessions.append(session)
        print(kind, label, 'passed', flush=True)
        share_test_windows(state, shared_windows)

    try:
        subprocess.run(['xrdb', '-merge'], input='Xft.dpi: 192\n', text=True, check=True)
        run(first_package, '1-original', preference=True)
        preference = workflow.preference(prefix()); assert preference not in (None, 'true', '0')
        first = prefix()
        initial_identity = _read_generations(state)
        for index in range(initial_relaunches):
            run(first_package, '1-initial-' + str(index + 1))
            assert prefix() == first and workflow.preference(first) == preference
            assert _read_generations(state) == initial_identity and sha(original) == original_hash
        internal = Path('drive_c/users/Public/Documents/onboarding.txt')
        (first / internal).parent.mkdir(parents=True, exist_ok=True); (first / internal).write_text('before update')
        if args.rollback_repair:
            from runtime.desktop_launch import plan_identity
            if kind in ('flatpak','appimage'):
                source_plan=json.loads(Path(str(baseline)+'.json').read_text())['plan']
            elif kind=='oci':
                from artifact.releases import oci_metadata
                source_plan=oci_metadata(baseline,'podman')[0]
            else:
                from runtime.container_state import managed_plan
                path=baseline/'metadata/native-launch.json'
                source_plan=json.loads(path.read_text()) if path.exists() else managed_plan(baseline)
            old_identity=_generation(_read_generations(state),_read_generations(state)['active'])['identity']
            assert plan_identity(source_plan)==old_identity
            old_executable=sha(first/workflow.executable)
            original_inventory=inventory_tree(first,state_snapshot=True)
            original_record=_read_generations(state)
            run(candidate,'2-repair','rollback-repair',baseline)
            repaired=prefix(); new_executable=sha(repaired/workflow.executable)
            new_identity=_generation(_read_generations(state),_read_generations(state)['active'])['identity']
            assert old_executable==new_executable and old_identity['runtimeDigest']!=new_identity['runtimeDigest']
            if args.application=='sumatrapdf':
                pins=json.loads((ROOT/'recipes/sumatrapdf-portable.releases.json').read_text())
                assert old_executable==pins['3.6']['executableSha256']
            assert workflow.preference(repaired)==preference and (repaired/internal).read_text()=='before update'
            run(candidate,'3-relaunch',preference=True,menu=True)
            assert workflow.preference(repaired)!=preference, 'qualify restoration, not merely identical preferences'
            (repaired/internal).write_text('latest document after update')
            run(candidate,'4-rollback-repair','rollback-repair',candidate)
            rolled=prefix()
            assert rolled!=repaired and workflow.preference(rolled)==preference
            assert (rolled/internal).read_text()=='latest document after update'
            assert workflow.preference(repaired)!=preference
            run(candidate,'5-relaunch',menu=True)
            for index in range(stress_relaunches):
                run(candidate,'6-repaired-stress-'+str(index+1))
                assert prefix()==rolled and workflow.preference(rolled)==preference
            assert inventory_tree(first,state_snapshot=True)==original_inventory
            record=_read_generations(state)
            assert all(entry in record['generations'] for entry in original_record['generations'])
            assert all(s['savedSha256']==original_hash for s in sessions)
            assert sha(original)==original_hash
        else:
            if legacy:
                run(baseline, '2-migrate', 'migrate', legacy)
                assert workflow.preference(prefix()) == preference
                journal = json.loads((state / 'legacy-migration.json').read_text()); snapshot = state / journal['snapshot']
                assert (snapshot / 'prefix' / internal).read_text() == 'before update'
                assert inventory_tree(first, state_snapshot=True) == inventory_tree(snapshot / 'prefix', state_snapshot=True)
            migrated = prefix()
            assert workflow.preference(migrated) == preference
            old_executable = sha(migrated / workflow.executable)
            old_identity = _generation(_read_generations(state), _read_generations(state)['active'])['identity']
            run(candidate, '3-update', 'update', baseline)
            updated = prefix(); new_executable = sha(updated / workflow.executable)
            assert updated != migrated
            if args.runtime_migration:
                assert new_executable == old_executable, 'update the application separately from its runtime'
                record = _read_generations(state); active = _generation(record, record['active'])
                new_identity = active['identity']
                assert old_identity['runtimeDigest'] != new_identity['runtimeDigest']
                assert active['runtimeMigration'] == {'from': old_identity, 'toRuntimeDigest': new_identity['runtimeDigest']}
            else:
                assert new_executable != old_executable
            if args.application == 'sumatrapdf':
                pins = json.loads((ROOT / 'recipes/sumatrapdf-portable.releases.json').read_text())
                assert old_executable == pins['3.6']['executableSha256']
                assert new_executable == pins['3.6' if args.runtime_migration else '3.6.1']['executableSha256']
            assert workflow.preference(updated) == preference and (updated / internal).read_text() == 'before update'
            (updated / internal).write_text('latest document after update')
            run(candidate, '4-relaunch', menu=True)
            assert prefix() == updated and workflow.preference(prefix()) == preference
            run(baseline, '5-rollback', 'rollback', candidate)
            assert sha(prefix() / workflow.executable) == old_executable and workflow.preference(prefix()) == preference
            assert (prefix() / internal).read_text() == 'latest document after update'
            assert (first / internal).read_text() == 'before update'
            rolled = prefix(); run(baseline, '6-relaunch', menu=True)
            assert prefix() == rolled and sha(original) == original_hash
            # Optional failure reproduction uses the same real workflow and exact
            # retained rollback target. A timeout fails immediately; nothing retries.
            for index in range(stress_relaunches):
                run(baseline, '7-stress-' + str(index + 1))
                assert prefix() == rolled and workflow.preference(prefix()) == preference
                assert sha(original) == original_hash
        result = {'status': 'passed', 'application': args.application, 'format': kind, 'architecture': os.uname().machine,
                  'pageSize': os.sysconf('SC_PAGE_SIZE'), 'sessions': sessions, 'legacyMigration': bool(legacy),
                  'settingsPreserved': True, 'documentsPreserved': True, 'rollback': True, 'menuRelaunch': kind in ('appimage', 'flatpak'),
                  'preference': preference, 'sourceExecutableHashes': {'baseline': old_executable, 'candidate': new_executable},
                  'generations': _read_generations(state), 'originalDocumentSha256': original_hash}
        assert source_identities()==original_sources,'source package/image changed during qualification'
        result.update(original_sources)
        if args.rollback_repair:
            result.update(qualificationKind='rollback-repair',repairSourcePlan=source_plan,
                rollbackRepairs=[{'from':old_identity,'to':new_identity}],
                originalGenerationsRetained=True,originalPrefixUnchanged=True,
                settingsRestoredFromOriginal=True,freshRuntimeSeed=True)
        if args.runtime_migration:
            result['runtimeMigrations'] = [{'from': old_identity, 'to': new_identity}]
        if stress_relaunches:result['stressRelaunches'] = stress_relaunches
        if initial_relaunches:result['initialRelaunches'] = initial_relaunches
        if args.trusted:
            info=json.loads(subprocess.check_output([sys.executable,'-m','cage','release','info',app,
                            '--key',str(key),'--format',kind,'--cache-dir',str(release_cache)],env=env,text=True))
            assert info['highWater']==2 and info['activeVersion']==baseline_version
            # No network is needed for retained, signed rollback/run history.
            server.shutdown();server.server_close();server=None
            subprocess.run([sys.executable,'-m','cage','release','info',app,'--key',str(key),
                            '--format',kind,'--cache-dir',str(release_cache)],env=env,check=True)
            result.update(trustedRelease=True,highWater=info['highWater'],retainedSignedReleases=info['retainedReleases'])
        (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if args.rollback_repair and not args.trusted and kind!='container':
            from artifact import releases
            producer=evidence/'producer';producer.mkdir()
            public=evidence/'publisher-public.pem'
            with tempfile.TemporaryDirectory(prefix='cage-repair-key-') as secret:
                private=Path(secret)/'private.pem';releases.generate_key(private,public)
                item={'format':kind,'path':str(candidate) if kind!='oci' else str(producer/'repair.oci.tar'),
                      'evidence':str(evidence/'result.json')}
                if kind=='oci':item['image']=candidate
                revision=os.environ.get('CAGE_TEST_SOURCE_REVISION') or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
                spec=producer/'repair.spec.json';spec.write_text(json.dumps({'sequence':2,'sourceRevision':revision,'artifacts':[item]}))
                release=producer/'repair.json';releases.create_release(spec,private,release)
                fetched=releases.fetch_release(release,public,kind,cache=release_cache)
                assert fetched['entry']['identity']==new_identity
                result['signedRepairFetch']={'releaseSha256':fetched['digest'],'sourceRevision':revision,
                    'scope':'signed repair package creation and fetch verification; not original-runtime qualification or installed trusted deployment'}
            (evidence/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        if kind == 'appimage':
            subprocess.run([installed['installed'], '--cage-uninstall'], env=env, check=True)
        if os.environ.get('CAGE_TEST_DISCARD_PREFIXES') == '1':shutil.rmtree(state)
        print(json.dumps({'status': 'passed', 'format': kind, 'sessions': len(sessions)}), flush=True)
    except BaseException:
        subprocess.run(['scrot', str(evidence / 'failure.png')], check=False)
        raise
    finally:
        if server:server.shutdown();server.server_close()
        # Close only windows owned by this proof, allowing Wine's launcher to
        # finish its normal shutdown even when an assertion failed.
        for handle in reversed(handles):
            visible = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', workflow.window_pattern], capture_output=True, text=True)
            if handle in visible.stdout.splitlines():
                subprocess.run(['xdotool', 'windowactivate', '--sync', handle], capture_output=True)
                subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Escape', 'alt+F4'], capture_output=True)
        for process in processes:
            if process.poll() is None:
                try:process.wait(timeout=30)
                except subprocess.TimeoutExpired:process.terminate()
        for output in logs:output.close()
        if kind in ('container', 'oci'):subprocess.run(['podman', 'rm', '-f', token], capture_output=True)


if __name__ == '__main__':main()
