#!/usr/bin/env python3
"""Exercise a real AppImage in an isolated X11 desktop; never the user's session."""
from pathlib import Path
import hashlib
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gui', ROOT / 'scripts/test-flatpak-poc.py')
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)
APP = gui.APP
EVIDENCE = Path(os.environ.get('CAGE_TEST_EVIDENCE', str(ROOT / 'dist/appimage-evidence'))).resolve()


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    package = Path(sys.argv[1]).resolve()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    original_hash = sha(package)
    data = EVIDENCE / 'consumer data café'
    if data.exists():
        raise AssertionError('use a fresh evidence directory for a clean consumer proof')
    data.mkdir()
    documents = EVIDENCE / 'documents with spaces'
    documents.mkdir()
    document = documents / 'AppImage café.txt'
    document.write_text('Original document\n')
    environment = {**os.environ, 'XDG_DATA_HOME': str(data)}
    # The caller selects FUSE or documented extraction fallback. The consumer
    # needs neither Wine nor Python: this Python process only drives GUI checks.
    if os.environ.get('CAGE_TEST_EXTRACT', '0') == '1':
        environment['APPIMAGE_EXTRACT_AND_RUN'] = '1'
        temporary = EVIDENCE / 'temporary'
        temporary.mkdir()
        environment['TMPDIR'] = str(temporary)
        atexit.register(shutil.rmtree, temporary, ignore_errors=True)
    info = subprocess.check_output([str(package), '--cage-info'], env=environment, text=True, timeout=180)
    plan = json.loads(info)
    installation = json.loads(subprocess.check_output([str(package), '--cage-install'],
                              env=environment, text=True, timeout=180))
    installed = Path(installation['installed'])
    assert sha(installed) == original_hash
    desktop = Path(installation['desktop'])
    logs = []
    def launch():
        log = (EVIDENCE / ('launch-' + str(len(logs) + 1) + '.log')).open('w')
        logs.append(log)
        # gio exercises the installed Exec escaping and file argument expansion.
        subprocess.run(['gio', 'launch', str(desktop), str(document)], env=environment,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
        handle = gui.wait_for(gui.window, 'real AppImage Notepad++ window', seconds=180)
        gui.wait_for(lambda: document.name in gui.command('xdotool', 'getwindowname', handle), 'Unicode document opened')
        gui.focus_editor(handle)
        return handle
    prefix = data / 'cage/appimage' / APP / 'prefix'
    def close():
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        gui.wait_for(lambda: subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', 'Notepad\\+\\+'],
            capture_output=True).returncode != 0, 'window closed without save prompt', seconds=45)
        # Acquire the application's own lock to prove Wine cleanup completed.
        import fcntl
        def lock_released():
            with (prefix.parent / 'launch.lock').open('r') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    return False
        gui.wait_for(lock_released, 'Wine services stopped and launch lock released', seconds=45)
    try:
        handle = launch()
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+a')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '15', 'Cage AppImage saved through the real application')
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        expected = 'Cage AppImage saved through the real application\n'
        gui.wait_for(lambda: document.read_text() == expected, 'exact saved host document')
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+v')
        gui.command('xdotool', 'key', '--delay', '80', 'Home', *(['Down'] * 6), 'Right', 'Home', 'Return')
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+s')
        subprocess.run(['scrot', str(EVIDENCE / 'first-save.png')], check=True)
        close()
        configs = list(prefix.glob('drive_c/users/*/AppData/Roaming/Notepad++/config.xml'))
        assert len(configs) == 1, configs
        config = configs[0]
        zoom = ET.parse(config).getroot().find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib['zoom']
        assert zoom != '0'
        before = (prefix.parent / 'state.json').read_bytes()
        # Relocate the source package, including spaces and Unicode, and launch
        # directly from that new path. Installed integration remains stable.
        moved = EVIDENCE / 'moved café % package.AppImage'
        shutil.copyfile(package, moved)
        moved.chmod(0o755)
        log = (EVIDENCE / 'relocated-launch.log').open('w')
        logs.append(log)
        process = subprocess.Popen([str(moved), str(document)], env=environment, stdout=log, stderr=subprocess.STDOUT)
        handle = gui.wait_for(gui.window, 'relocated AppImage window', seconds=180)
        gui.wait_for(lambda: document.name in gui.command('xdotool', 'getwindowname', handle), 'reopened original file')
        gui.focus_editor(handle)
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+End')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '15', 'Relaunch verified')
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        gui.wait_for(lambda: document.read_text() == expected + 'Relaunch verified\n', 'reopened text preserved and extended')
        subprocess.run(['scrot', str(EVIDENCE / 'relaunch.png')], check=True)
        close()
        assert process.wait(timeout=180) == 0
        assert (prefix.parent / 'state.json').read_bytes() == before
        assert ET.parse(config).getroot().find(".//GUIConfig[@name='ScintillaPrimaryView']").attrib['zoom'] == zoom
        assert sha(package) == original_hash and sha(installed) == original_hash
        subprocess.run([str(installed), '--cage-uninstall'], env=environment, check=True, timeout=180)
        assert not desktop.exists() and not installed.exists()
        assert config.exists() and document.read_text() == expected + 'Relaunch verified\n'
        result = {'schemaVersion': 'cage.appimage-functional-test/v0', 'status': 'passed',
            'packageSha256': original_hash, 'architecture': plan['target']['architecture'],
            'kernelPageSize': os.sysconf('SC_PAGE_SIZE'), 'host': gui.command('uname', '-srmo'),
            'install': True, 'desktopLaunch': True, 'save': True, 'relaunch': True, 'relocation': True,
            'sameStateGeneration': True, 'settingsZoom': zoom, 'uninstallRetainsState': True,
            'savedContents': document.read_text(), 'mode': 'extract-and-run' if environment.get('APPIMAGE_EXTRACT_AND_RUN') else 'FUSE',
            'minimumGlibc': plan['target']['minimumGlibc'], 'runtimeTarget': plan['target']}
        (EVIDENCE / 'functional-test.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
    except BaseException:
        subprocess.run(['scrot', str(EVIDENCE / 'failure.png')], check=False)
        raise
    finally:
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
