"""CI diagnostics retain proof records without following Wine drives/user data."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
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
def test_go_dump_only_signals_the_failed_ci_launchers_direct_podman_child(tmp_path, monkeypatch, parent):
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
         patch.object(Path, 'read_text', read), patch.object(module.os, 'kill') as kill, \
         patch.object(module.shutil, 'which', return_value=None), patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
        module.shutdown_diagnostics(SimpleNamespace(pid=99999999), tmp_path / 'shutdown', 'app.exe', container_state=tmp_path)
    if parent == 99999999:kill.assert_called_once_with(99999998, signal.SIGQUIT)
    else:kill.assert_not_called()
