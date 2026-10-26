#!/usr/bin/env python3
"""Host-only failure observer; leaves the clean consumer and proof gates intact."""
from pathlib import Path
from types import SimpleNamespace
import argparse
import importlib.util
import json
import os
import subprocess
import time


def host_targets(container, request):
    """Resolve only matching live processes in this exact rootless container."""
    details = json.loads(subprocess.check_output(['podman', 'inspect', container], text=True, timeout=10))[0]
    if details['Id'] != container or not details['State']['Running']:
        raise RuntimeError('proof container is not running')
    mapping = subprocess.check_output(['podman', 'top', container, 'hpid', 'pid'], text=True, timeout=10)
    by_pid = {int(row[1]): int(row[0]) for line in mapping.splitlines()[1:] if len(row := line.split()) == 2}
    targets = []
    for target in request['targets']:
        pid = by_pid.get(target['pid'])
        if pid is None:raise RuntimeError('failed application is no longer in proof container')
        root = Path('/proc') / str(pid)
        if (root.stat().st_uid != os.getuid()
                or (root / 'comm').read_text().strip().casefold() != Path(request['executable']).name[:15].casefold()
                or (root / 'stat').read_text().rsplit(')', 1)[1].split()[19] != target['startTime']):
            raise RuntimeError('failed application process identity changed')
        targets.append(pid)
    return targets


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cidfile', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('command', nargs=argparse.REMAINDER)
    args = p.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if os.environ.get('GITHUB_ACTIONS') != 'true' or args.cidfile.exists():
        p.error('requires CI and a fresh proof container ID file')
    cid_index = command.index('--cidfile') if '--cidfile' in command else -1
    if command[:2] != ['podman', 'run'] or cid_index < 0 or command[cid_index + 1:cid_index + 2] != [str(args.cidfile)]:
        p.error('observer must own the podman run and its exact cidfile')
    spec = importlib.util.spec_from_file_location('proof', Path(__file__).with_name('test-onboarding-poc.py'))
    proof = importlib.util.module_from_spec(spec); spec.loader.exec_module(proof)
    process = subprocess.Popen(command)
    observed = set()
    while process.poll() is None:
        if args.evidence.is_dir():
            for request in args.evidence.glob('*-host-request.json'):
                if request in observed:continue
                observed.add(request)
                try:
                    if request.is_symlink() or request.stat().st_size > 4096:raise RuntimeError('unsafe diagnostic request')
                    container = args.cidfile.read_text().strip()
                    data = json.loads(request.read_text())
                    for pid in host_targets(container, data):
                        proof.shutdown_diagnostics(SimpleNamespace(pid=pid),
                            request.with_name(request.stem + '-' + str(pid)), data['executable'], kernel=True)
                except Exception as exc:
                    request.with_suffix('.error.log').write_text(str(exc) + '\n')
                finally:request.with_suffix('.done').write_text('diagnostic complete; trial remains failed\n')
        time.sleep(.2)
    raise SystemExit(process.returncode)


if __name__ == '__main__':main()
