#!/usr/bin/env python3
"""Real GUI update/rollback proof shared by Flatpak, AppImage and native OCI.

Requires generation-aware baseline/candidate exports of pinned 8.8.8/8.8.9.
Runs in a private X11 desktop. Never uses the user's normal application state.
"""
from pathlib import Path
import hashlib
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
from runtime.desktop_launch import digest_json


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    kind, baseline, candidate = sys.argv[1:4]
    baseline, candidate = Path(baseline).resolve(), Path(candidate).resolve()
    evidence = Path(os.environ['CAGE_TEST_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    token = 'cage-update-proof-' + uuid.uuid4().hex
    documents = Path.home() / 'Documents/Cage' / token if kind == 'flatpak' else evidence / 'documents'
    documents.mkdir(parents=True)
    document = documents / 'Update café.txt'
    document.write_text('original\n')
    installed = None
    if kind == 'appimage':
        env['XDG_DATA_HOME'] = str(evidence / 'data')
        installed = json.loads(subprocess.check_output([str(baseline), '--cage-install'], env=env, text=True))
        state = evidence / 'data/cage/appimage' / gui.APP
    elif kind == 'flatpak':
        subprocess.run(['flatpak', 'install', '--user', '--noninteractive', '-y', '--no-related', '--no-deps',
                        '--bundle', str(baseline)], env=env, check=True)
        # A private store's override isolates this proof from the real user data.
        subprocess.run(['flatpak', 'override', '--user', '--env=XDG_DATA_HOME=/var/data/' + token, gui.APP], env=env, check=True)
        state = Path.home() / '.var/app' / gui.APP / 'data' / token / gui.APP
    elif kind == 'container':
        state = evidence / 'state' / gui.APP
    else:
        raise ValueError('unknown adapter')
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
            return ['flatpak', 'run', '--user', gui.APP, str(document)]
        return [sys.executable, '-m', 'cage', 'run', str(package), str(document), '--engine', 'podman',
                '--graphics', 'desktop', '--state-dir', str(state.parent), '--writable-files',
                '--name', token, *(['--state-action', action] if action else [])]
    processes, handles = [], []
    def start(package, action=None):
        log = (evidence / (str(len(processes)) + '-' + (action or 'launch') + '.log')).open('w')
        handles.append(log)
        process = subprocess.Popen(command(package, action), env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        handle = gui.wait_for(gui.window, 'Notepad++ ' + (action or 'launch'), seconds=180)
        gui.wait_for(lambda: document.name in gui.command('xdotool', 'getwindowname', handle), 'document loaded')
        gui.focus_editor(handle)
        return process
    def save(text):
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+a')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '10', text)
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        gui.wait_for(lambda: document.read_text() == text + '\n', 'exact saved document')
    def close(process):
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        assert process.wait(timeout=90) == 0, 'launcher failed; see retained log'
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
    def executable_hash():
        return sha(prefix() / 'drive_c/Program Files/Notepad++/notepad++.exe')
    source_hashes = {}
    for version in ('8.8.8', '8.8.9'):
        with zipfile.ZipFile(ROOT / ('sources/npp.' + version + '.portable.x64.zip')) as archive:
            source_hashes[version] = hashlib.sha256(archive.read('notepad++.exe')).hexdigest()
    try:
        process = start(baseline)
        save('saved before update')
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+v')
        gui.command('xdotool', 'key', '--delay', '80', 'Home', *(['Down'] * 6), 'Right', 'Home', 'Return')
        subprocess.run(['scrot', str(evidence / 'baseline.png')], check=True)
        close(process)
        first = prefix()
        assert executable_hash() == source_hashes['8.8.8']
        original_zoom = zoom()
        assert original_zoom != '0'
        account = config().relative_to(first).parts[2]
        relative = Path('drive_c/users') / account / 'Documents/local.txt'
        (first / relative).write_text('prefix document before update')
        process = start(candidate, 'update')
        save('saved after update')
        subprocess.run(['scrot', str(evidence / 'update.png')], check=True)
        close(process)
        updated = prefix()
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
        (evidence / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        print(json.dumps(result, indent=2))
        if os.environ.get('CAGE_TEST_DISCARD_PREFIXES') == '1':
            shutil.rmtree(state)  # Only this proof's fresh, private state root.
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        if kind == 'container':
            subprocess.run(['podman', 'rm', '-f', token], capture_output=True)
        for handle in handles:
            handle.close()


if __name__ == '__main__':
    main()
