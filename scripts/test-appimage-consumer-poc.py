#!/usr/bin/env python3
"""Clean distro userland qualification of the actual AppImage, not a boot test."""
from pathlib import Path
import importlib.util
import atexit
import json
import os
import socket
import shutil
import subprocess
import sys
from appimage_consumer import consumer_glibc, private_runtime_maps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proof_storage import ProofPayloads
spec = importlib.util.spec_from_file_location('gui', ROOT / 'scripts/test-flatpak-poc.py')
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def main():
    package, image = Path(sys.argv[1]).resolve(), sys.argv[2]
    libc = consumer_glibc(image)
    original_package = package
    relocated_package = package.with_name('Relocated café ' + package.name)
    evidence = Path(os.environ['CAGE_TEST_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    data, home, temporary = [evidence / name for name in ['data', 'home', 'temporary']]
    for path in (data, home, temporary):
        path.mkdir()
    atexit.register(shutil.rmtree, temporary, ignore_errors=True)
    document = evidence / 'Consumer café file.txt'
    document.write_text('Original consumer document\n')
    prefix = data / 'cage/appimage' / gui.APP
    payloads = ProofPayloads(prefix, evidence)
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
    argv += [image, 'sh', '-ec',
             'if command -v wine || command -v python3; then '
             'echo "consumer must not have Wine or Python installed" >&2; exit 1; fi; exec "$@"',
             'cage-consumer']
    logs = []
    def launch():
        log = (evidence / ('launch-' + str(len(logs) + 1) + '.log')).open('w')
        logs.append(log)
        process = subprocess.Popen([*argv, str(package), str(document)], stdout=log, stderr=subprocess.STDOUT)
        handle = gui.wait_for(gui.window, 'clean consumer Notepad++ window', seconds=180)
        gui.wait_for(lambda: document.name in gui.command('xdotool', 'getwindowname', handle), 'requested consumer document')
        gui.focus_editor(handle)
        return process
    try:
        process = launch()
        maps = private_runtime_maps(container_name)
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+a')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '15', 'Clean consumer AppImage saved')
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        expected = 'Clean consumer AppImage saved\n'
        gui.wait_for(lambda: document.read_text() == expected, 'consumer exact saved document')
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        assert process.wait(timeout=180) == 0
        payloads.record()
        before = (prefix / 'state.json').read_bytes()
        package.rename(relocated_package)
        package = relocated_package
        process = launch()
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+End')
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '15', 'Consumer relaunch verified')
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return', 'ctrl+s')
        gui.wait_for(lambda: document.read_text() == expected + 'Consumer relaunch verified\n', 'consumer reopened original text')
        subprocess.run(['scrot', str(evidence / 'relaunch.png')], check=True)
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
        assert process.wait(timeout=180) == 0
        payloads.record()
        assert (prefix / 'state.json').read_bytes() == before
        result = {'schemaVersion': 'cage.appimage-consumer-test/v0', 'status': 'passed',
            'consumerImage': image, 'consumerImageId': gui.command('podman', 'image', 'inspect', '--format', '{{.Id}}', image),
            'consumerGlibc': libc, 'privateRuntimeMaps': maps, 'packageRelocated': True,
            'kernelPageSize': os.sysconf('SC_PAGE_SIZE'), 'bootedDistroQualification': False,
            'consumerWineInstalled': False, 'consumerPythonInstalled': False,
            'save': True, 'relaunch': True, 'sameStateGeneration': True, 'savedContents': document.read_text(),
            'mode': 'extract-and-run', 'host': gui.command('uname', '-srmo')}
        (evidence / 'functional-test.json').write_text(json.dumps(result, indent=2) + '\n')
        payloads.finish()
        print(json.dumps(result, indent=2))
    except BaseException:
        subprocess.run(['scrot', str(evidence / 'failure.png')], check=False)
        raise
    finally:
        subprocess.run(['podman', 'rm', '-f', container_name], capture_output=True, timeout=30)
        if package == relocated_package:
            package.rename(original_package)
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
