"""The CI observer may inspect only the failed consumer's unchanged process."""
from pathlib import Path
import importlib.util
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('mismatch', [None, 'container', 'stopped', 'pid', 'owner', 'name', 'start'])
def test_host_resolution_requires_exact_container_and_process_identity(tmp_path, monkeypatch, mismatch):
    observer = load('observer', 'observe-appimage-proof.py', monkeypatch)
    container = 'a' * 64
    def output(command, **kwargs):
        if command[1] == 'inspect':
            return json.dumps([{'Id': 'other' if mismatch == 'container' else container,
                                'State': {'Running': mismatch != 'stopped'}}])
        return 'HPID PID\n123 17\n' if mismatch != 'pid' else 'HPID PID\n123 18\n'
    read = Path.read_text; stat = Path.stat
    def read_proc(path, *args, **kwargs):
        if path == Path('/proc/123/comm'):return 'other' if mismatch == 'name' else 'SumatraPDF.exe\n'
        if path == Path('/proc/123/stat'):return '123 (SumatraPDF.exe) ' + ' '.join(['0'] * 19 + ['999' if mismatch == 'start' else '42'])
        return read(path, *args, **kwargs)
    def stat_proc(path, *args, **kwargs):
        if path == Path('/proc/123'):return SimpleNamespace(st_uid=observer.os.getuid() + (mismatch == 'owner'))
        return stat(path, *args, **kwargs)
    with patch.object(observer.subprocess, 'check_output', side_effect=output), \
         patch.object(Path, 'read_text', read_proc), patch.object(Path, 'stat', stat_proc):
        request = {'executable': 'drive_c/SumatraPDF.exe', 'targets': [{'pid': 17, 'startTime': '42'}]}
        if mismatch:
            with pytest.raises(RuntimeError):observer.host_targets(container, request)
        else:assert observer.host_targets(container, request) == [123]


def test_failure_request_contains_only_application_identity_and_times_out_boundedly(tmp_path, monkeypatch):
    proof = load('proof_failure', 'test-onboarding-poc.py', monkeypatch)
    monkeypatch.setenv('CAGE_TEST_HOST_DIAGNOSTICS', '1')
    monkeypatch.setenv('GITHUB_ACTIONS', 'false')
    read = Path.read_text
    def read_proc(path, *args, **kwargs):
        if path == Path('/proc/999999/comm'):return 'SumatraPDF.exe\n'
        if path == Path('/proc/999999/stat'):return '999999 (SumatraPDF.exe) ' + ' '.join(['0'] * 19 + ['42'])
        return read(path, *args, **kwargs)
    with patch.object(Path, 'read_text', read_proc), patch.object(proof.time, 'monotonic', side_effect=[0, 61]):
        proof.shutdown_diagnostics(SimpleNamespace(pid=999999), tmp_path / 'failed', 'drive_c/SumatraPDF.exe')
    request = tmp_path / 'failed-host-request.json'
    assert json.loads(request.read_text()) == {'executable': 'drive_c/SumatraPDF.exe', 'targets': [{'pid': 999999, 'startTime': '42'}]}
    assert not request.with_suffix('.tmp').exists()
    assert not (tmp_path / 'result.json').exists()


@pytest.mark.parametrize('code', [0, 1, 73])
def test_observer_preserves_actual_child_exit_status_without_requests(tmp_path, monkeypatch, code):
    observer = load('observer_exit', 'observe-appimage-proof.py', monkeypatch)
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    cidfile = tmp_path / 'consumer.cid'
    evidence = tmp_path / 'evidence'; evidence.mkdir()
    monkeypatch.setattr(sys, 'argv',
                        ['observer', '--cidfile', str(cidfile), '--evidence', str(evidence),
                         '--', 'podman', 'run', '--cidfile', str(cidfile), 'proof'])
    child = SimpleNamespace(poll=lambda: code, returncode=code)
    with patch.object(observer.subprocess, 'Popen', return_value=child), pytest.raises(SystemExit) as result:
        observer.main()
    assert result.value.code == code
