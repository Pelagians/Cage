#!/usr/bin/env python3
"""CI-only native shutdown sampling; never qualification or release signing."""
from pathlib import Path
import hashlib
import json
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import time


def capture(record_path, executable, destination):
    if os.environ.get('GITHUB_ACTIONS') != 'true':raise RuntimeError('owned shutdown capture requires CI')
    record = json.loads(Path(record_path).read_text()); destination = Path(destination)
    if record.get('diagnosticOnly') is not True or record.get('observerChangesTiming') is not True:
        raise RuntimeError('shutdown capture requires a non-qualifying observer record')
    apps = [p for p in record['processes'] if p['comm'] == Path(executable).name[:15].casefold()]
    if len(apps) != 1:raise RuntimeError('shutdown capture requires one owned application')
    app = apps[0]; root = Path('/proc') / str(app['hostPid'])
    try:
        uid = root.stat().st_uid
        birth = (root / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        name = (root / 'comm').read_text().strip().casefold()
    except OSError:return False
    if uid != record['ownerUid'] or birth != app['startTime'] or name != app['comm']:
        raise RuntimeError('owned application identity changed before capture')
    candidates = sorted(Path('/usr/lib/linux-tools').glob('*/perf'))
    if not candidates:raise RuntimeError('native sampling requires the packaged perf executable')
    perf = str(candidates[-1]); children = []; descriptors = []; pipes = []; libraries = []; skipped = []; total = 0
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT, stop)
    data = destination.with_name(destination.name + '-profile.perf')
    symbols = destination.parent / 'native-symbols'
    try:
        # Pin mapped runtime ELF descriptors across --rm. Read their contents
        # for symbolization only AFTER a failed trial, retaining original bytes.
        paths = {line.split(maxsplit=5)[-1] for line in app['maps'].splitlines() if len(line.split(maxsplit=5)) == 6}
        for path in sorted(paths):
            if not path.startswith(('/usr/lib/', '/usr/lib64/', '/lib/', '/lib64/')) or '..' in Path(path).parts:continue
            try:
                fd = os.open(str(root / 'root') + path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 256 * 1024**2 or total + info.st_size > 512 * 1024**2 or os.read(fd, 4) != b'\x7fELF':
                    os.close(fd); skipped.append(path); continue
                total += info.st_size; os.lseek(fd, 0, os.SEEK_SET); descriptors.append((path, fd))
            except OSError:skipped.append(path)
        ctl = destination.with_name(destination.name + '-control.fifo'); ack = destination.with_name(destination.name + '-ack.fifo')
        for path in (ctl, ack):
            os.mkfifo(path, 0o600); pipes.append((path, os.open(path, os.O_RDWR | os.O_NONBLOCK)))
        with destination.with_name(destination.name + '-perf.log').open('w') as log:
            # perf 6.8 selects VG from a hardware-PMU probe on SVE hosts, but
            # the software clock PMU rejects extended registers. Keep the
            # ordinary AArch64 registers needed for native DWARF unwinding.
            recorder = subprocess.Popen([perf, 'record', '-e', 'cpu-clock:u', '-F', '99', '--call-graph', 'dwarf,8192',
                '--user-regs=' + ','.join([*('x' + str(i) for i in range(30)), 'lr', 'sp', 'pc']),
                '--namespaces', '--delay=-1', '--control=fifo:' + str(ctl) + ',' + str(ack),
                '-p', str(app['hostPid']), '-o', str(data)], stdout=log, stderr=subprocess.STDOUT)
            children.append(recorder); os.write(pipes[0][1], b'enable\n')
            if not select.select([pipes[1][1]], [], [], 10)[0] or os.read(pipes[1][1], 64).rstrip(b'\n\0') != b'ack':
                raise RuntimeError('native sampling did not acknowledge enabled events')
            trace = subprocess.Popen(['strace', '-f', '-ttt', '-i', '-e', 'trace=%process,%signal,futex,close',
                '-o', str(destination.with_suffix('.log')),
                *[arg for pid in record['targets'] for arg in ('-p', str(pid))]], stdout=log, stderr=subprocess.STDOUT)
            children.append(trace); limit = time.monotonic() + 10
            while any('\nTracerPid:\t0\n' in '\n' + Path('/proc', str(pid), 'status').read_text() for pid in record['targets']):
                if trace.poll() is not None or time.monotonic() > limit:raise RuntimeError('owned signal trace did not attach')
                time.sleep(.02)
            destination.with_name(destination.name + '-attached').touch()
            while not stopped:
                if recorder.poll() is not None or trace.poll() is not None:
                    try:alive = (root / 'stat').read_text().rsplit(')', 1)[1].split()[19] == app['startTime']
                    except OSError:alive = False
                    if alive:raise RuntimeError('native observer exited while its owned application was alive')
                time.sleep(.02)
            for child in children:child.wait(timeout=10)
        outcome = json.loads(destination.with_name(destination.name + '-outcome.json').read_text())
        if outcome['exitCode'] != 0:
            for path, fd in descriptors:
                target = symbols / path.lstrip('/'); target.parent.mkdir(parents=True, exist_ok=True)
                with os.fdopen(os.dup(fd), 'rb') as source, target.open('wb') as output:shutil.copyfileobj(source, output)
                with target.open('rb') as source:digest = hashlib.file_digest(source, 'sha256').hexdigest()
                libraries.append({'path': path, 'sha256': digest})
        symbols.mkdir(exist_ok=True)
        with destination.with_name(destination.name + '-profile.log').open('w') as output:
            subprocess.run([perf, 'script', '-i', str(data), '--symfs', str(symbols), '--max-stack', '64'],
                           stdout=output, stderr=subprocess.STDOUT, timeout=30, check=True)
        destination.with_name(destination.name + '-profile.json').write_text(json.dumps({
            'schemaVersion': 'cage.shutdown-profile/v1', 'diagnosticOnly': True, 'observerChangesTiming': True,
            'pid': app['hostPid'], 'startTime': app['startTime'], 'exitCode': outcome['exitCode'],
            'event': 'cpu-clock:u', 'frequencyHz': 99, 'registers': 'ordinary AArch64; no extended SVE registers', 'symbols': libraries,
            'skippedSymbols': skipped, 'bytes': data.stat().st_size}, indent=2) + '\n')
    finally:
        for child in children:
            if child.poll() is None:child.send_signal(signal.SIGINT); child.wait(timeout=10)
        for _, fd in descriptors:os.close(fd)
        for path, fd in pipes:os.close(fd); path.unlink()
    return True


if __name__ == '__main__':capture(*sys.argv[1:])
