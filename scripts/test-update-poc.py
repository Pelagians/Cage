#!/usr/bin/env python3
"""Real GUI update/rollback proof for Flatpak, AppImage, bundles and OCI images.

Requires generation-aware baseline/candidate exports of pinned 8.8.8/8.8.9.
Runs in a private X11 desktop. Never uses the user's normal application state.
"""
from pathlib import Path
import hashlib
import configparser
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('gui', ROOT / 'scripts/test-flatpak-poc.py')
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)
from application_workflows import share_test_windows
from proof_storage import ProofPayloads


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    kind, baseline, candidate = sys.argv[1:4]
    image_ids = None
    if kind == 'oci':
        image_ids = {name: subprocess.check_output(
            ['podman', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
            for name, image in (('baseline', baseline), ('candidate', candidate))}
        baseline, candidate = image_ids['baseline'], image_ids['candidate']
    else:
        baseline, candidate = Path(baseline).resolve(), Path(candidate).resolve()
    source_packages={name:sha(value) for name,value in (('baseline',baseline),('candidate',candidate))} if kind in ('flatpak','appimage') else None
    evidence = Path(os.environ['CAGE_TEST_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    token = 'cage-update-proof-' + uuid.uuid4().hex
    documents = Path.home() / 'Documents/Cage' / token if kind == 'flatpak' else evidence / 'documents'
    documents.mkdir(parents=True)
    document = documents / 'Update café.txt'
    document.write_text('original\n')
    desktop_proof = kind in ('flatpak', 'appimage') and os.environ.get('CAGE_TEST_DESKTOP_INTEGRATION') == '1'
    readonly = None
    if desktop_proof:
        selected = evidence / 'selected files'
        selected.mkdir()
        document = selected / 'Read only café.txt'
        document.write_text('original read-only document\n')
        document.chmod(0o444)
        readonly = document
        (selected / 'unselected.txt').write_text('not selected for the sandbox')
    installed = None
    flatpak_desktop = None
    if kind == 'appimage':
        env['XDG_DATA_HOME'] = str(evidence / 'data')
        state = evidence / 'data/cage/appimage' / gui.APP
    elif kind == 'flatpak':
        subprocess.run(['flatpak', 'install', '--user', '--noninteractive', '--reinstall', '-y', '--no-related', '--no-deps',
                        '--bundle', str(baseline)], env=env, check=True)
        # Flatpak resets reserved XDG variables after applying host overrides.
        # Set the private path inside the sandbox, then exec the real packaged
        # command. Keep the normal installed user's data completely untouched.
        private = Path.home() / '.var/app' / gui.APP / 'data' / token
        state = private / gui.APP
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read_string(subprocess.check_output(['flatpak', 'info', '--user', '--show-metadata', gui.APP],
                                                     env=env, text=True))
        assert metadata['Application']['command'] == 'cage-desktop-launch'
        actual_flatpak = shutil.which('flatpak')
        shim = evidence / 'tools'
        shim.mkdir()
        (shim / 'flatpak').write_text('#!/usr/bin/env python3\nimport os,sys\n'
            + 'real=' + repr(actual_flatpak) + '\nprivate=' + repr(str(private)) + '\n'
            + 'args=sys.argv[1:]\n'
            + 'if args[:1]==["run"] and all(not a.startswith("--command=") or a=="--command=cage-desktop-launch" for a in args):\n'
            + '    positions=[i for i,a in enumerate(args) if a.split("/")[0]==' + repr(gui.APP) + ']\n'
            + '    if len(positions)==1:\n'
            + '        pos=positions[0]\n'
            + '        flags=[a for a in args[1:pos] if not a.startswith("--command=")]\n'
            + '        args=["run",*flags,"--command=sh",args[pos],"-c",'
            + repr('export XDG_DATA_HOME="$1"; shift; exec /app/bin/cage-desktop-launch "$@"')
            + ',"cage-proof",private,*args[pos+1:]]\n'
            + 'os.execv(real,[real,*args])\n')
        (shim / 'flatpak').chmod(0o755)
        env['PATH'] = str(shim) + os.pathsep + env['PATH']
        if desktop_proof:
            store = Path(env['FLATPAK_USER_DIR'])
            original = store / 'exports/share/applications' / (gui.APP + '.desktop')
            contents = original.read_text()
            assert '--file-forwarding' in contents and '@@ %F @@' in contents
            assert 'MimeType=text/plain;' in contents
            flatpak_desktop = evidence / 'private.desktop'
            # The exported file-forwarding command is retained. Only the runner
            # is replaced to set XDG_DATA_HOME inside the sandbox, protecting the
            # normal user's settings. No filesystem permissions are added.
            runner = '"' + str(shim / 'flatpak').replace('\\','\\\\').replace('"','\\"') + '"'
            contents = contents.replace('Exec=' + actual_flatpak + ' ', 'Exec=' + runner + ' ')
            flatpak_desktop.write_text(contents)
            subprocess.run([actual_flatpak, 'run', '--user', '--command=python3', gui.APP, '-c',
                            'from pathlib import Path; import sys; assert not Path(sys.argv[1]).exists()',
                            str(readonly.parent / 'unselected.txt')], env=env, check=True)

    elif kind in ('container', 'oci'):
        state = evidence / 'state' / gui.APP
        state.parent.mkdir()
    else:
        raise ValueError('unknown adapter')
    payloads = ProofPayloads(state, evidence)
    if kind == 'appimage':
        installed = json.loads(subprocess.check_output([str(baseline), '--cage-install'], env=env, text=True))
    def prefix():
        record = json.loads((state / 'state.json').read_text())
        return state / record['active'] if record.get('schemaVersion') == 'cage.desktop-generations/v1' else state / 'prefix'
    def config():
        matches = list(prefix().glob('drive_c/users/*/AppData/Roaming/Notepad++/config.xml'))
        assert len(matches) == 1, matches
        return matches[0]
    def zoom():
        return ET.parse(config()).find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib['zoom']
    def command(package, action=None):
        if kind == 'appimage':
            if not action and installed:
                return ['gio', 'launch', installed['desktop'], str(document)]
            return [str(package), *(['--cage-' + action] if action else []), '--', str(document)]
        if kind == 'flatpak':
            if action:
                previous = baseline if action == 'update' else candidate
                return [sys.executable, '-m', 'cage', 'rollback' if action == 'rollback' else 'update',
                        'flatpak', str(package), '--previous-package', str(previous),
                        '--cache-dir', str(evidence / 'package-cache'), str(document)]
            if flatpak_desktop:
                return ['gio', 'launch', str(flatpak_desktop), str(document)]
            return ['flatpak', 'run', '--user', gui.APP, str(document)]
        if kind == 'oci':
            return ['podman', 'run', '--rm', '--pull=never', '--name', token,
                    '--userns=keep-id', '--user', '0:0', '--net=none',
                    '--hostname', os.uname().nodename, '--security-opt', 'label=disable',
                    '-e', 'PUID=' + str(os.getuid()), '-e', 'PGID=' + str(os.getgid()),
                    '-e', 'DISPLAY', '-e', 'XAUTHORITY=/tmp/cage-xauthority',
                    '-v', env['XAUTHORITY'] + ':/tmp/cage-xauthority:ro',
                    '-v', '/tmp/.X11-unix:/tmp/.X11-unix:ro',
                    '-v', str(state.parent) + ':/var/lib/cage/state',
                    '-v', str(documents) + ':/exports', str(package),
                    *(['--cage-' + action] if action else []), '--', '/exports/' + document.name]
        return [sys.executable, '-m', 'cage', 'run', str(package), str(document), '--engine', 'podman',
                '--graphics', 'desktop', '--state-dir', str(state.parent), '--writable-files',
                '--name', token, *(['--state-action', action] if action else [])]
    processes, handles = [], []
    def start(package, action=None):
        creating = desktop_proof and not document.exists()
        confirmed = False
        log = (evidence / (str(len(processes)) + '-' + (action or 'launch') + '.log')).open('w')
        handles.append(log)
        process = subprocess.Popen(command(package, action), env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        handle = gui.wait_for(gui.window, 'Notepad++ ' + (action or 'launch'), seconds=180)
        def loaded():
            nonlocal confirmed
            if document.name in gui.command('xdotool', 'getwindowname', handle):
                return True
            if creating and not confirmed:
                dialog = subprocess.run(['xdotool','search','--onlyvisible','--name','^Create new file$'],
                                        capture_output=True,text=True)
                if dialog.returncode == 0:
                    subprocess.run(['scrot', str(evidence / 'create-new-file-confirmation.png')], check=True)
                    gui.command('xdotool','windowactivate','--sync',dialog.stdout.splitlines()[-1])
                    gui.command('xdotool','key','--clearmodifiers','alt+y')
                    confirmed = True
            return False
        gui.wait_for(loaded, 'document loaded')
        gui.focus_editor(handle)
        return process
    def save(text):
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+a')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '10', text)
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        gui.wait_for(lambda: document.read_text() == text + '\n', 'exact saved document')
    shared_windows = set()
    def close(process):
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        assert process.wait(timeout=90) == 0, 'launcher failed; see retained log'
        assert (state / 'state.json').is_file(), 'expected persistent app state is missing; check the sandbox XDG path'
        import fcntl
        def stopped():
            with (state / 'launch.lock').open() as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    return False
        gui.wait_for(stopped, 'Wine cleanup', seconds=60)
        gui.wait_for(lambda: not subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', 'Notepad\\+\\+'],
                    capture_output=True).stdout, 'GUI shutdown')
        share_test_windows(state, shared_windows)
        payloads.record()
    def executable_hash():
        assert not (prefix() / "drive_c/Program Files/Notepad++/updater").exists(), "bundled self-updater must be excluded"
        return sha(prefix() / 'drive_c/Program Files/Notepad++/notepad++.exe')
    source_hashes = {}
    for version in ('8.8.8', '8.8.9'):
        with zipfile.ZipFile(ROOT / ('sources/npp.' + version + '.portable.x64.zip')) as archive:
            source_hashes[version] = hashlib.sha256(archive.read('notepad++.exe')).hexdigest()
    def dpi_check():
        if desktop_proof:
            sys.path.insert(0, str(ROOT))
            from runtime.desktop_launch import prefix_dpi
            assert prefix_dpi(prefix()) == 192, 'expected 2x logical DPI in the actual Wine prefix'
            assert '"Courier New"="Liberation Mono"' in (prefix() / 'user.reg').read_text(), 'Windows monospace fallback missing'
    try:
        if desktop_proof:
            subprocess.run(['xrdb', '-merge'], input='Xft.dpi: 192\n', text=True, check=True)
            control = [str(baseline)] if kind == 'appimage' else ['flatpak','run','--user',gui.APP]
            subprocess.run([*control, '--cage-dpi', 'auto'], env=env, check=True)
            info = json.loads(subprocess.check_output([*control, '--cage-display-info'], env=env, text=True))
            assert info['hostDpi'] == 192, info
            if installed:
                assert 'MimeType=text/plain;' in Path(installed['desktop']).read_text()
        process = start(baseline)
        if desktop_proof:
            saved = documents / 'Saved As document.txt'
            # Use the pinned application's File > Save As accelerator. Ctrl+Shift+S
            # is Save All in Notepad++, so it cannot qualify Save As behavior.
            gui.command('xdotool','key','--clearmodifiers','alt+f')
            gui.command('xdotool','key','--clearmodifiers','a')
            subprocess.run(['scrot', str(evidence / 'save-as-request.png')],check=True)
            gui.wait_for(lambda: gui.command('xdotool','search','--onlyvisible','--name','^Save As$'), 'Save As dialog')
            gui.command('xdotool','key','--clearmodifiers','ctrl+a')
            gui.command('xdotool','type','--clearmodifiers','--delay','10','Z:'+str(saved).replace('/','\\'))
            subprocess.run(['scrot', str(evidence / 'save-as-dialog.png')],check=True)
            gui.command('xdotool','key','--clearmodifiers','Return')
            gui.wait_for(lambda: saved.exists(), 'Save As created new host document')
            document = saved
            gui.wait_for(lambda: saved.name in gui.command('xdotool','getwindowname',gui.window()), 'Save As returned to the document')
            gui.focus_editor(gui.window())
            assert readonly.read_text() == 'original read-only document\n'
        save('saved before update')
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+v')
        gui.command('xdotool', 'key', '--delay', '80', 'Home', *(['Down'] * 6), 'Right', 'Home', 'Return')
        subprocess.run(['scrot', str(evidence / 'baseline.png')], check=True)
        close(process)
        first = prefix()
        dpi_check()
        assert executable_hash() == source_hashes['8.8.8']
        original_zoom = zoom()
        assert original_zoom != '0'
        # Cross-host Wine seeds may map the current login's Documents to the
        # host. Exercise prefix-document migration in an ordinary seed account
        # instead; a proof fixture must never write through a host-folder link.
        local_folders = [p for p in first.glob('drive_c/users/*/Documents')
                         if p.is_dir() and not p.is_symlink() and not p.parent.is_symlink()
                         and p.resolve().is_relative_to(first.resolve())]
        assert local_folders, 'proof requires an ordinary in-prefix Documents directory'
        relative = local_folders[0].relative_to(first) / 'local.txt'
        (first / relative).write_text('prefix document before update')
        process = start(candidate, 'update')
        save('saved after update')
        subprocess.run(['scrot', str(evidence / 'update.png')], check=True)
        close(process)
        updated = prefix()
        dpi_check()
        assert updated != first
        assert executable_hash() == source_hashes['8.8.9'], 'old program survived update'
        assert zoom() == original_zoom, 'settings were not migrated'
        assert (updated / relative).read_text() == 'prefix document before update'
        (updated / relative).write_text('latest prefix document after update')
        process = start(candidate)
        save('saved on updated relaunch')
        close(process)
        assert prefix() == updated
        process = start(baseline, 'rollback')
        save('saved after rollback')
        subprocess.run(['scrot', str(evidence / 'rollback.png')], check=True)
        close(process)
        restored = prefix()
        dpi_check()
        assert restored not in (first, updated)
        assert executable_hash() == source_hashes['8.8.8']
        assert zoom() == original_zoom
        assert (restored / relative).read_text() == 'latest prefix document after update'
        assert (first / relative).read_text() == 'prefix document before update'
        process = start(baseline)
        save('saved on rollback relaunch')
        close(process)
        assert prefix() == restored
        assert document.read_text() == 'saved on rollback relaunch\n'
        if desktop_proof:
            previous = document
            document = documents / 'New from launcher café.txt'
            process = start(baseline)
            save('new file created by the application')
            close(process)
            assert previous.read_text() == 'saved on rollback relaunch\n'
            assert readonly.read_text() == 'original read-only document\n'
            document = previous
            dpi_check()
            # A selected writable file outside the permanent Flatpak grant must
            # support in-place save and reopen, not just read-only import.
            document = readonly.parent / 'Writable café.txt'
            document.write_text('original writable document\n')
            process = start(baseline)
            save('saved selected writable file')
            close(process)
            process = start(baseline)
            gui.command('xdotool','key','--clearmodifiers','ctrl+End')
            gui.command('xdotool','type','--clearmodifiers','--delay','10','reopened selected writable file')
            gui.command('xdotool','key','--clearmodifiers','ctrl+s')
            gui.wait_for(lambda: document.read_text() == 'saved selected writable file\nreopened selected writable file',
                         'selected writable file reopened and appended')
            close(process)
            assert readonly.read_text() == 'original read-only document\n'
            document = previous
        if installed:
            subprocess.run([installed['installed'], '--cage-uninstall'], env=env, check=True)
            assert (state / 'state.json').is_file()
        result = {'status': 'passed', 'format': kind, 'architecture': os.uname().machine,
                  'pageSize': os.sysconf('SC_PAGE_SIZE'), 'versions': ['8.8.8', '8.8.9', '8.8.8'],
                  'sourceExecutableHashes': source_hashes, 'settingsZoom': original_zoom,
                  'generations': json.loads((state / 'state.json').read_text()),
                  'externalDocument': str(document), 'externalDocumentContents': document.read_text(),
                  'prefixDocumentsCarriedForward': True, 'originalGenerationsRetained': True,
                  'saveAndRelaunchAfterUpdateAndRollback': True}
        result.update(settingsPreserved=True,documentsPreserved=True,rollback=True)
        if source_packages:
            assert source_packages=={name:sha(value) for name,value in (('baseline',baseline),('candidate',candidate))}
            result['sourceArtifactHashes']=source_packages
        if desktop_proof:
            result['desktopIntegration'] = {'mimeHandler': True, 'desktopFileForwarding': kind == 'flatpak', 'readOnlyOriginalPreserved': True, 'saveAs': True, 'newFileFromLauncher': True, 'selectedWritableSaveAndRelaunch': True, 'logicalDpi': 192, 'dpiPreservedAcrossUpdateAndRollback': True}
        if image_ids:
            result['ociImageIds'] = image_ids
            result['sourceImageIds'] = image_ids
        (evidence / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        print(json.dumps(result, indent=2))
        payloads.finish()
    except BaseException:
        subprocess.run(['scrot', str(evidence / 'failure.png')], check=False)
        windows = subprocess.run(['xdotool','search','--onlyvisible','--name','.*'], capture_output=True, text=True)
        titles = {}
        for handle in windows.stdout.splitlines():
            title = subprocess.run(['xdotool','getwindowname',handle],capture_output=True,text=True)
            titles[handle] = title.stdout.strip()
        (evidence / 'failure-windows.json').write_text(json.dumps(titles,indent=2)+'\n')
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        if kind in ('container', 'oci'):
            subprocess.run(['podman', 'rm', '-f', token], capture_output=True)
        for handle in handles:
            handle.close()


if __name__ == '__main__':
    main()
