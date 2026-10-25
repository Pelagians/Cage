#!/usr/bin/env python3
"""CI-only native capture while an owned Wine server is stopped before SIGKILL.

Debugger timing is diagnostic and can never produce qualification evidence.
The caller already verified the private state mount; retain the exact PID birth
identity so an exited application's recycled PID cannot be inspected.
"""
from pathlib import Path
import importlib.util
import json
import os
import sys
from types import SimpleNamespace


def capture(record_path, executable, destination):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('owned shutdown capture requires CI')
    record = json.loads(Path(record_path).read_text())
    if record.get('diagnosticOnly') is not True or record.get('observerChangesTiming') is not True:
        raise RuntimeError('shutdown capture requires a non-qualifying observer record')
    app = [p for p in record['processes'] if p['comm'] == Path(executable).name[:15].casefold()]
    if len(app) != 1:raise RuntimeError('shutdown capture requires one owned application')
    app = app[0]; root = Path('/proc') / str(app['hostPid'])
    try:
        uid = root.stat().st_uid
        birth = (root / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        name = (root / 'comm').read_text().strip().casefold()
    except OSError:return False
    if uid != record['ownerUid'] or birth != app['startTime'] or name != app['comm']:
        raise RuntimeError('owned application identity changed before capture')
    spec = importlib.util.spec_from_file_location('onboarding', Path(__file__).with_name('test-onboarding-poc.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.shutdown_diagnostics(SimpleNamespace(pid=app['hostPid'], poll=lambda: None),
                                Path(destination), executable)
    return True


if __name__ == '__main__':
    capture(*sys.argv[1:])
