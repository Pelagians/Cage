#!/usr/bin/env python3
"""Shared real GUI proof: legacy adoption, update, save/relaunch and rollback.

Only fresh private state is used. Application-specific actions live in the small
workflow drivers; format adapters share the same lifecycle assertions.
"""
from pathlib import Path
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.desktop_launch import inventory_tree, _read_generations, _generation, lifecycle_lock
from application_workflows import WORKFLOWS
spec = importlib.util.spec_from_file_location('gui', ROOT / 'scripts/test-flatpak-poc.py')
gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('format', choices=['flatpak', 'appimage', 'container', 'oci'])
    parser.add_argument('baseline'); parser.add_argument('candidate')
    parser.add_argument('--legacy'); parser.add_argument('--application', choices=WORKFLOWS, default='sumatrapdf')
    args = parser.parse_args(); kind = args.format; workflow = WORKFLOWS[args.application]()
    app = workflow.app_id
    baseline, candidate = (Path(p).resolve() if kind != 'oci' else p for p in (args.baseline, args.candidate))
    legacy = (args.legacy if kind == 'oci' else Path(args.legacy).resolve()) if args.legacy else None
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
    if kind == 'flatpak':
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
    def share_windows():
        # Optional local Btrfs test-space optimization, never enabled by CI or
        # production launch. Kernel equality checks preserve every private file.
        source = os.environ.get('CAGE_TEST_SHARE_WINDOWS')
        if not source:return
        with lifecycle_lock(state):
            before = (state / 'state.json').read_bytes()
            for entry in _read_generations(state)['generations']:
                if entry['prefix'] in shared_windows:continue
                windows = state / entry['prefix'] / 'drive_c/windows'
                for target in windows.rglob('*'):
                    src = Path(source) / target.relative_to(windows)
                    if target.is_symlink() or src.is_symlink() or not target.is_file() or not src.is_file():continue
                    size = target.stat().st_size
                    if size < 1024**2 or size != src.stat().st_size:continue
                    with src.open('rb') as a, target.open('r+b') as b:
                        data = bytearray(struct.pack('=QQHHI', 0, size, 1, 0, 0) + struct.pack('=qQQiI', b.fileno(), 0, 0, 0, 0))
                        fcntl.ioctl(a.fileno(), 0xc0189436, data, True)
                        if struct.unpack_from('=i', data, 48)[0] not in (0, 1):raise RuntimeError('extent verification refused')
                shared_windows.add(entry['prefix'])
            assert before == (state / 'state.json').read_bytes()

    processes = []; handles = []; logs = []; sessions = []
    def run(package, label, action=None, previous=None, preference=False, menu=False):
        nonlocal document
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
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        assert process.wait(timeout=120) == 0, 'application/launcher failed; retained log'
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
        sessions.append({'phase': label, 'identity': active['identity'], 'prefix': record['active'], 'savedSha256': sha(saved)})
        print(kind, label, 'passed', flush=True)
        share_windows()

    try:
        subprocess.run(['xrdb', '-merge'], input='Xft.dpi: 192\n', text=True, check=True)
        run(first_package, '1-original', preference=True)
        preference = workflow.preference(prefix()); assert preference not in (None, 'true', '0')
        first = prefix()
        internal = Path('drive_c/users/Public/Documents/onboarding.txt')
        (first / internal).parent.mkdir(parents=True, exist_ok=True); (first / internal).write_text('before update')
        if legacy:
            run(baseline, '2-migrate', 'migrate', legacy)
            assert workflow.preference(prefix()) == preference
            journal = json.loads((state / 'legacy-migration.json').read_text()); snapshot = state / journal['snapshot']
            assert (snapshot / 'prefix' / internal).read_text() == 'before update'
            assert inventory_tree(first, state_snapshot=True) == inventory_tree(snapshot / 'prefix', state_snapshot=True)
        migrated = prefix()
        assert workflow.preference(migrated) == preference
        old_executable = sha(migrated / workflow.executable)
        run(candidate, '3-update', 'update', baseline)
        updated = prefix(); new_executable = sha(updated / workflow.executable)
        assert updated != migrated and new_executable != old_executable
        if args.application == 'sumatrapdf':
            pins = json.loads((ROOT / 'recipes/sumatrapdf-portable.releases.json').read_text())
            assert old_executable == pins['3.6']['executableSha256']
            assert new_executable == pins['3.6.1']['executableSha256']
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
        result = {'status': 'passed', 'application': args.application, 'format': kind, 'architecture': os.uname().machine,
                  'pageSize': os.sysconf('SC_PAGE_SIZE'), 'sessions': sessions, 'legacyMigration': bool(legacy),
                  'settingsPreserved': True, 'documentsPreserved': True, 'rollback': True, 'menuRelaunch': kind in ('appimage', 'flatpak'),
                  'preference': preference, 'sourceExecutableHashes': {'baseline': old_executable, 'candidate': new_executable},
                  'generations': _read_generations(state), 'originalDocumentSha256': original_hash}
        (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if kind == 'appimage':
            subprocess.run([installed['installed'], '--cage-uninstall'], env=env, check=True)
        if os.environ.get('CAGE_TEST_DISCARD_PREFIXES') == '1':shutil.rmtree(state)
        print(json.dumps({'status': 'passed', 'format': kind, 'sessions': len(sessions)}), flush=True)
    except BaseException:
        subprocess.run(['scrot', str(evidence / 'failure.png')], check=False)
        raise
    finally:
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
