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


@pytest.mark.parametrize('name,maps,expected', [
    ('app.exe', '/usr/lib64/wine/aarch64-unix/ntdll.so', True),
    ('app.exe', '/usr/lib64/wine/x86_64-unix/ntdll.so', False),
    ('podman', '/usr/lib64/wine/aarch64-unix/ntdll.so', False),
])
def test_saved_arm_context_only_captured_for_owned_wine_application(tmp_path, monkeypatch, name, maps, expected):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_arm_stack', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    real_read = Path.read_text
    def read(path, *args, **kwargs):
        if path == Path('/proc/99999998/comm'):return name + '\n'
        if path == Path('/proc/99999998/maps'):return maps
        if path == Path('/proc/99999998/status'):return 'PPid:\t99999999\n'
        return real_read(path, *args, **kwargs)
    with patch.object(module, 'proof_container_processes', return_value=([{'id': 'owned'}], [99999998])), \
         patch.object(Path, 'read_text', read), patch.object(module.subprocess, 'run') as debugger, \
         patch.object(module.shutil, 'which', side_effect=lambda tool: '/usr/bin/gdb' if tool == 'gdb' else None), \
         patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
        module.shutdown_diagnostics(SimpleNamespace(pid=99999999), tmp_path / 'shutdown', 'app.exe', container_state=tmp_path)
    debugger.assert_called_once()
    args = debugger.call_args.args[0]
    assert args[args.index('-p') + 1] == '99999998' and args[-1] == 'detach'
    assert any('$cage_frame' in arg for arg in args) is expected
    if expected:
        assert 'x/102gx $cage_frame' in args  # Exactly the pinned 0x330-byte frame.
        assert 'x/512gx *(unsigned long long*)($cage_frame+0xf8)' in args
        assert 'x/128gx *(unsigned long long*)($cage_frame+0xe8)' in args
        assert 'x/8hx *(unsigned long long*)($cage_frame+0xa8)' in args
        assert debugger.call_args.kwargs['timeout'] == 30


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
            if path.name == 'status':return f'TracerPid:\t999\nNSpid:\t{pid}\t{pid - 90}\n'
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
        record = json.loads((tmp_path / 'trace.json').read_text())
        assert record['container'] == 'owned' and record['targets'] == [101, 102]
        assert record['processes'] == [
            {'hostPid': pid, 'comm': name.casefold(), 'namespacePids': [pid, pid - 90]}
            for pid, name in names.items()]


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


def test_idle_failure_finds_detached_proof_lock_holder_and_preserves_failure(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_idle', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setenv('GITHUB_ACTIONS', 'false')
    state = tmp_path / 'proof'; state.mkdir()
    unrelated = tmp_path / 'other-proof'; unrelated.mkdir()
    code = ('import fcntl,sys,time\n'
            'with open(sys.argv[1], "w") as lock:\n'
            ' fcntl.flock(lock,fcntl.LOCK_EX);print("ready",flush=True);time.sleep(60)\n')
    children = []
    try:
        for folder in (state, unrelated):
            child = subprocess.Popen([sys.executable, '-c', code, str(folder / 'launch.lock')],
                                     stdout=subprocess.PIPE, text=True)
            children.append(child)
            assert child.stdout.readline() == 'ready\n'
        def timeout(condition, description, *, seconds):
            assert seconds == 60 and condition() is False
            raise AssertionError('timed out: ' + description)
        destination = tmp_path / '6-relaunch-idle'
        with patch.object(module.gui, 'wait_for', side_effect=timeout):
            # The menu launcher is already gone; its private lease is the
            # ownership boundary for discovering the surviving Wine process.
            with pytest.raises(AssertionError, match='Wine stopped and state committed'):
                module.wait_for_idle(SimpleNamespace(pid=99999999, poll=lambda: 0), state, destination, 'app.exe')
        record = json.loads((tmp_path / '6-relaunch-idle-lock.json').read_text())
        assert record['processes'] == [children[0].pid]
        records = json.loads(destination.with_suffix('.json').read_text())
        assert {r['pid'] for r in records} == {children[0].pid}
        error = json.loads((tmp_path / '6-relaunch-idle-error.json').read_text())
        assert 'already running' in error['lastLockError']
    finally:
        for child in children:
            child.terminate(); child.wait(timeout=5); child.stdout.close()


@pytest.mark.parametrize('linked_state', [False, True])
def test_proof_lock_discovery_refuses_linked_state_or_lock(tmp_path, monkeypatch, linked_state):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_linked_lock', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    state = tmp_path / 'proof'; state.mkdir(); (state / 'launch.lock').write_text('')
    if linked_state:
        alias = tmp_path / 'alias'; alias.symlink_to(state); state = alias
    else:
        (state / 'launch.lock').unlink(); (state / 'launch.lock').symlink_to(tmp_path / 'outside')
    with pytest.raises(RuntimeError, match='must not be linked'):
        module.proof_lock_processes(state)


def test_idle_diagnostic_error_does_not_replace_original_failure(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('onboarding_idle_error', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with patch.object(module.gui, 'wait_for', side_effect=AssertionError('original idle timeout')), \
         patch.object(module, 'shutdown_diagnostics', side_effect=OSError('collector unavailable')):
        with pytest.raises(AssertionError, match='original idle timeout'):
            module.wait_for_idle(SimpleNamespace(pid=99999999), tmp_path, tmp_path / 'idle', 'app.exe')
    assert (tmp_path / 'idle-diagnostic-error.log').read_text() == 'collector unavailable'
