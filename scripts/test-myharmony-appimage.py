#!/usr/bin/env python3
"""Exercise MyHarmony's actual x86_64 AppImage in a selected clean userland."""
from pathlib import Path
import atexit
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from PIL import Image
from appimage_consumer import consumer_glibc, private_runtime_maps

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gui', ROOT / 'scripts/test-flatpak-poc.py')
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)
APP = 'io.github.Pelagians.Cage.MyHarmony'


def main():
    package = Path(sys.argv[1]).resolve()
    image = sys.argv[2] if len(sys.argv) > 2 else 'registry.fedoraproject.org/fedora:44'
    libc = consumer_glibc(image)
    original_package = package
    relocated_package = package.with_name('Relocated café ' + package.name)
    evidence = Path(os.environ['CAGE_TEST_EVIDENCE']).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    data, home, temporary = [evidence / name for name in ('data', 'home', 'temporary')]
    for path in (data, home, temporary):
        path.mkdir()
    atexit.register(shutil.rmtree, temporary, ignore_errors=True)
    state = data / 'cage/appimage' / APP
    name = 'cage-myharmony-proof-' + str(os.getpid())
    argv = ['podman', 'run', '--rm', '--name', name, '--network', 'bridge', '--userns=keep-id',
        '--user', f'{os.getuid()}:{os.getgid()}', '--hostname', socket.gethostname(),
        '--security-opt', 'label=disable', '-v', str(ROOT) + ':' + str(ROOT) + ':ro',
        '-v', str(evidence) + ':' + str(evidence) + ':rw',
        '-v', '/tmp/.X11-unix:/tmp/.X11-unix:ro', '-e', 'DISPLAY=' + os.environ['DISPLAY'],
        '-e', 'HOME=' + str(home), '-e', 'XDG_DATA_HOME=' + str(data),
        '-e', 'TMPDIR=' + str(temporary), '-e', 'APPIMAGE_EXTRACT_AND_RUN=1',
        '-e', 'WINEDEBUG=+wininet,+winhttp,+schannel']
    if os.environ.get('XAUTHORITY'):
        argv += ['-v', os.environ['XAUTHORITY'] + ':/tmp/cage-xauthority:ro',
                 '-e', 'XAUTHORITY=/tmp/cage-xauthority']
    argv += [image, 'sh', '-ec', 'if command -v wine || command -v python3; then exit 1; fi; exec "$@"', 'consumer', str(package)]
    logs = []
    process = None
    def window():
        if process is not None and process.poll() is not None:
            raise AssertionError('AppImage exited before opening its window: ' + str(process.returncode))
        errors = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Server error$'], capture_output=True, text=True)
        if errors.returncode == 0:
            raise AssertionError('MyHarmony reported a service connection error')
        return gui.command('xdotool', 'search', '--onlyvisible', '--name', '^MyHarmony$').splitlines()[-1]
    try:
        before = None
        for run in (1, 2):
            log = (evidence / f'launch-{run}.log').open('w')
            logs.append(log)
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
            handle = gui.wait_for(window, 'normal MyHarmony window', seconds=180)
            gui.command('xdotool', 'windowactivate', '--sync', handle)
            screenshot = evidence / f'window-{run}.png'
            def rendered():
                if process.poll() is not None:
                    raise AssertionError('MyHarmony terminated during startup')
                subprocess.run(['scrot', '-u', str(screenshot)], check=True)
                # The live Silverlight screen has large blue, dark and white areas.
                # Blank CEF windows and Wine's empty desktop cannot satisfy this.
                pixels = list(Image.open(screenshot).convert('RGB').resize((160, 100)).getdata())
                return (sum(b > 110 and b > r * 1.25 and g > r * 1.15 for r,g,b in pixels) > 800
                    and sum(max(r,g,b) < 70 for r,g,b in pixels) > 800
                    and sum(min(r,g,b) > 220 for r,g,b in pixels) > 800)
            gui.wait_for(rendered, 'rendered online Logitech interface', seconds=180)
            maps = private_runtime_maps(name)
            user_reg = (state / 'prefix/user.reg').read_text(errors='replace')
            assert '"Desktop"="MyHarmony"' not in user_reg
            assert 'Explorer\\\\Desktops' not in user_reg
            system_reg = (state / 'prefix/system.reg').read_text(errors='replace')
            assert 'Arial (TrueType)' in system_reg and 'Trebuchet MS (TrueType)' in system_reg
            marker = state / 'prefix/drive_c/myharmony-persistence-test.txt'
            if run == 1:
                marker.write_text('Keep application state across launches\n')
            else:
                assert marker.read_text() == 'Keep application state across launches\n'
            gui.command('xdotool', 'key', '--clearmodifiers', 'alt+F4')
            assert process.wait(timeout=180) == 0
            record = (state / 'state.json').read_bytes()
            if before is not None:
                assert record == before
            before = record
            if run == 1:
                package.rename(relocated_package)
                package = relocated_package
                argv[-1] = str(package)
        result = {'status': 'passed', 'architecture': 'x86_64', 'consumerImage': image,
            'consumerImageId': gui.command('podman', 'image', 'inspect', '--format', '{{.Id}}', image),
            'normalWindow': True, 'onlineInterfaceRendered': True, 'relaunch': True,
            'sameStateGeneration': True, 'persistentUserFile': True,
            'consumerGlibc': libc, 'privateRuntimeMaps': maps, 'packageRelocated': True,
            'hostWineRequired': False, 'hostPythonRequired': False,
            'physicalUsbDetectionQualified': False, 'physicalSynchronizationQualified': False}
        (evidence / 'functional-test.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
    except BaseException:
        subprocess.run(['scrot', str(evidence / 'failure.png')], check=False)
        raise
    finally:
        subprocess.run(['podman', 'rm', '-f', name], capture_output=True, timeout=30)
        if package == relocated_package:
            package.rename(original_package)
        for log in logs:
            log.close()
        for basename in ('debug.log', 'console.log'):
            source = state / 'prefix/drive_c/MyHarmony' / basename
            if source.is_file():
                (evidence / ('myharmony-' + basename)).write_bytes(source.read_bytes()[-160000:])
        for log in evidence.glob('launch-*.log'):
            if log.stat().st_size > 400000:
                content = log.read_bytes()
                log.write_bytes(content[:100000] + b'\n[bounded diagnostic excerpt]\n' + content[-300000:])


if __name__ == '__main__':
    main()
