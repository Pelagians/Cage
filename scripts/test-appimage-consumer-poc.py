#!/usr/bin/env python3
"""Clean distro userland qualification of the actual AppImage, not a boot test."""
from pathlib import Path
import importlib.util
import json
import os
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gui', ROOT / 'scripts/test-flatpak-poc.py')
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def main():
    package, image = Path(sys.argv[1]).resolve(), sys.argv[2]
    evidence = Path(os.environ['CAGE_TEST_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    data, home, temporary = [evidence / name for name in ['data', 'home', 'temporary']]
    for path in (data, home, temporary):
        path.mkdir()
    document = evidence / 'Consumer café file.txt'
    document.write_text('Original consumer document\n')
    prefix = data / 'cage/appimage' / gui.APP
    container_name = 'cage-appimage-proof-' + str(os.getpid())
    argv = ['podman', 'run', '--rm', '--name', container_name, '--network', 'none', '--userns=keep-id',
        '--user', str(os.getuid()) + ':' + str(os.getgid()), '--hostname', socket.gethostname(),
        '--security-opt', 'label=disable', '-v', str(ROOT) + ':' + str(ROOT) + ':ro',
        '-v', str(evidence) + ':' + str(evidence) + ':rw',
        '-v', '/tmp/.X11-unix:/tmp/.X11-unix:ro', '-e', 'DISPLAY=' + os.environ['DISPLAY'],
        '-e', 'HOME=' + str(home), '-e', 'XDG_DATA_HOME=' + str(data),
        '-e', 'TMPDIR=' + str(temporary), '-e', 'APPIMAGE_EXTRACT_AND_RUN=1']
    if os.environ.get('XAUTHORITY'):
        auth = os.environ['XAUTHORITY']
        argv += ['-v', auth + ':/tmp/cage-xauthority:ro', '-e', 'XAUTHORITY=/tmp/cage-xauthority']
    argv += [image, 'sh', '-ec', '! command -v wine; ! command -v python3; exec "$@"', 'cage-consumer']
    logs = []
    def launch():
        log = (evidence / ('launch-' + str(len(logs) + 1) + '.log')).open('w')
        logs.append(log)
        process = subprocess.Popen([*argv, str(package), str(document)], stdout=log, stderr=subprocess.STDOUT)
        handle = gui.wait_for(gui.window, 'clean consumer Notepad++ window', seconds=180)
        gui.command('xdotool', 'windowactivate', '--sync', handle)
        gui.wait_for(lambda: document.name in gui.command('xdotool', 'getwindowname', handle), 'requested consumer document')
        return process
    try:
        process = launch()
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+a')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '15', 'Clean consumer AppImage saved')
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        expected = 'Clean consumer AppImage saved\n'
        gui.wait_for(lambda: document.read_text() == expected, 'consumer exact saved document')
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        assert process.wait(timeout=180) == 0
        before = (prefix / 'state.json').read_bytes()
        process = launch()
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+End')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '15', 'Consumer relaunch verified')
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        gui.wait_for(lambda: document.read_text() == expected + 'Consumer relaunch verified\n', 'consumer reopened original text')
        subprocess.run(['scrot', str(evidence / 'relaunch.png')], check=True)
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        assert process.wait(timeout=180) == 0
        assert (prefix / 'state.json').read_bytes() == before
        result = {'schemaVersion': 'cage.appimage-consumer-test/v0', 'status': 'passed',
            'consumerImage': image, 'consumerImageId': gui.command('podman', 'image', 'inspect', '--format', '{{.Id}}', image),
            'kernelPageSize': os.sysconf('SC_PAGE_SIZE'), 'bootedDistroQualification': False,
            'consumerWineInstalled': False, 'consumerPythonInstalled': False,
            'save': True, 'relaunch': True, 'sameStateGeneration': True, 'savedContents': document.read_text(),
            'mode': 'extract-and-run', 'host': gui.command('uname', '-srmo')}
        (evidence / 'functional-test.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
    except BaseException:
        subprocess.run(['scrot', str(evidence / 'failure.png')], check=False)
        raise
    finally:
        subprocess.run(['podman', 'rm', '-f', container_name], capture_output=True, timeout=30)
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
