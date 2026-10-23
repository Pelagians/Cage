"""CI diagnostics retain proof records without following Wine drives/user data."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / 'scripts/collect-onboarding-evidence.py'


def test_collector_cli_retains_records_without_user_state_or_drive_links(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'private.json').write_text('private')
    expected = {'result.json', 'run.log', 'failure.png', 'publisher-public.pem', 'trusted-cache/releases/one/release.json.sig'}
    for name in expected:
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(name)
    for name in ('state', 'data', 'documents', 'package-cache'):
        path = source / name; path.mkdir(); (path / 'private.json').write_text('private')
    (source / 'z:').symlink_to(outside, target_is_directory=True)
    (source / 'linked.json').symlink_to(outside / 'private.json')
    (source / 'publisher-private.pem').write_text('private')
    destination = tmp_path / 'collected'
    subprocess.run([sys.executable, str(COLLECTOR), '--source', str(source), '--destination', str(destination)], check=True)
    assert {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()} == expected
    assert all((destination / name).read_text() == name for name in expected)
    assert (outside / 'private.json').read_text() == 'private'
    assert (source / 'z:').is_symlink() and (source / 'state/private.json').read_text() == 'private'


@pytest.mark.parametrize('linked', [False, True])
def test_collector_refuses_recursive_destination_or_linked_root(tmp_path, linked):
    source = tmp_path / 'source'; source.mkdir()
    if linked:
        alias = tmp_path / 'alias'; alias.symlink_to(source); source = alias
    result = subprocess.run([sys.executable, str(COLLECTOR), '--source', str(source),
                             '--destination', str(source / 'output')], capture_output=True, text=True)
    assert result.returncode != 0
    assert not (source / 'output').exists()


def test_shutdown_diagnostics_only_includes_container_with_exact_proof_mount(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_proof', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    state = tmp_path / 'state'; calls = []
    def command(args, **kwargs):
        calls.append(args)
        if args[1] == 'ps':return 'owned\nother\n'
        if args[1] == 'inspect':
            return json.dumps([{'Mounts': [{'Source': str(state) if args[2] == 'owned' else '/another-state',
                                           'Destination': '/var/lib/cage/state'}]}])
        assert args == ['podman', 'top', 'owned', 'hpid']
        return 'HPID\n99999998\n'
    destination = tmp_path / 'failed-shutdown'
    with patch.object(module.subprocess, 'check_output', side_effect=command), patch.dict(module.os.environ, {'GITHUB_ACTIONS': 'false'}):
        module.shutdown_diagnostics(SimpleNamespace(pid=99999999), destination, 'notepad++.exe', container_state=state)
    records = json.loads(destination.with_suffix('.json').read_text())
    assert {record['pid'] for record in records} == {99999998, 99999999}
    containers = json.loads(destination.with_name(destination.name + '-containers.json').read_text())
    assert [item['id'] for item in containers] == ['owned']
    assert ['podman', 'top', 'other', 'hpid'] not in calls
    assert calls[0] == ['podman', 'ps', '--all', '--filter', 'volume=/var/lib/cage/state', '--format', '{{.ID}}']


@pytest.mark.parametrize('parent', [99999999, 1])
def test_debugger_only_attaches_to_the_failed_ci_launchers_direct_podman_child(tmp_path, monkeypatch, parent):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_dump', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    real_read = Path.read_text
    def read(path, *args, **kwargs):
        if path == Path('/proc/99999998/comm'):return 'podman\n'
        if path == Path('/proc/99999998/status'):return 'PPid:\t' + str(parent) + '\n'
        return real_read(path, *args, **kwargs)
    def command(args, **kwargs):
        if args[1] == 'ps':return 'owned\n'
        if args[1] == 'inspect':return json.dumps([{'Mounts': [{'Source': str(tmp_path), 'Destination': '/var/lib/cage/state'}]}])
        return 'HPID\n99999998\n'
    with patch.object(module.subprocess, 'check_output', side_effect=command), \
         patch.object(Path, 'read_text', read), patch.object(module.subprocess, 'run') as debugger, \
         patch.object(module.shutil, 'which', return_value='/usr/bin/gdb'), patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
        module.shutdown_diagnostics(SimpleNamespace(pid=99999999), tmp_path / 'shutdown', 'app.exe', container_state=tmp_path)
    if parent == 99999999:
        debugger.assert_called_once()
        args = debugger.call_args.args[0]
        assert args[args.index('-p') + 1] == '99999998'
        assert 'thread apply all bt' in args and 'detach' in args
    else:debugger.assert_not_called()


@pytest.mark.parametrize('ci', ['true', 'false'])
def test_failure_kernel_records_are_bounded_and_ci_only(tmp_path, monkeypatch, ci):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_kernel', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    destination = tmp_path / 'failure'
    with patch.object(module.subprocess, 'run', return_value=SimpleNamespace(stdout='x' * (300 * 1024), stderr='warning')) as command, \
         patch.object(module.shutil, 'which', return_value=None), patch.dict(os.environ, {'GITHUB_ACTIONS': ci}):
        module.shutdown_diagnostics(SimpleNamespace(pid=99999999), destination, 'app.exe', kernel=True)
    kernel = tmp_path / 'failure-kernel.log'
    if ci == 'true':
        command.assert_called_once_with(['sudo', '-n', 'dmesg', '--color=never', '--ctime'],
                                        capture_output=True, text=True, timeout=10, check=False)
        assert len(kernel.read_text()) == 256 * 1024 and kernel.read_text().endswith('warning')
        assert set(json.loads((tmp_path / 'failure-memory.json').read_text())) == {'memory.events', 'memory.current', 'memory.peak'}
    else:
        command.assert_not_called()
        assert not kernel.exists() and not (tmp_path / 'failure-memory.json').exists()


def test_shutdown_trace_is_ci_only_and_opt_in(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_trace', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.delenv('CAGE_TEST_TRACE_SHUTDOWN', raising=False)
    with patch.object(module.subprocess, 'Popen') as launch:
        with module.shutdown_trace(tmp_path / 'trace', 'app.exe', None):pass
        launch.assert_not_called()
        monkeypatch.setenv('CAGE_TEST_TRACE_SHUTDOWN', '1')
        monkeypatch.setenv('GITHUB_ACTIONS', 'false')
        with pytest.raises(RuntimeError, match='requires CI'):
            with module.shutdown_trace(tmp_path / 'trace', 'app.exe', tmp_path):pass
        launch.assert_not_called()


def test_shutdown_trace_attaches_only_owned_wine_and_detaches_on_failure(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_trace_owned', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setenv('CAGE_TEST_TRACE_SHUTDOWN', '1'); monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    names = {101: 'SumatraPDF.exe', 102: 'wineserver64', 103: 'podman', 104: 'python3'}
    real_read = Path.read_text
    def read(path, *args, **kwargs):
        if path.parent.parent == Path('/proc'):
            pid = int(path.parent.name)
            if path.name == 'comm':return names[pid] + '\n'
            if path.name == 'status':return 'TracerPid:\t999\n'
        return real_read(path, *args, **kwargs)
    with patch.object(module, 'proof_container_processes', return_value=([{'id': 'owned'}], list(names))), \
         patch.object(Path, 'read_text', read), patch.object(module.shutil, 'which', return_value='/usr/bin/strace'), \
         patch.object(module.subprocess, 'Popen') as launch, patch.object(module.subprocess, 'run') as detach:
        observer = launch.return_value; observer.pid = 999; observer.poll.return_value = None
        detach.return_value.returncode = 0
        with pytest.raises(subprocess.TimeoutExpired):
            with module.shutdown_trace(tmp_path / 'trace', 'SumatraPDF.exe', tmp_path):
                raise subprocess.TimeoutExpired('application', 120)
        args = launch.call_args.args[0]
        assert args[-4:] == ['-p', '101', '-p', '102']
        assert launch.call_args.kwargs['start_new_session'] is True
        detach.assert_called_once_with(['sudo', '-n', 'kill', '-INT', '--', '-999'], capture_output=True, timeout=10)
        observer.wait.assert_called_once_with(timeout=10)


def test_shutdown_trace_refuses_ambiguous_container_ownership(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_trace_ambiguous', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setenv('CAGE_TEST_TRACE_SHUTDOWN', '1'); monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    with patch.object(module, 'proof_container_processes', return_value=([{'id': 'one'}, {'id': 'two'}], [])), \
         patch.object(module.shutil, 'which', return_value='/usr/bin/strace'), patch.object(module.subprocess, 'Popen') as launch:
        with pytest.raises(RuntimeError, match='cannot identify'):
            with module.shutdown_trace(tmp_path / 'trace', 'app.exe', tmp_path):pass
        launch.assert_not_called()
