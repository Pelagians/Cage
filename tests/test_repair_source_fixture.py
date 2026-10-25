"""Repair qualification never needs to launch the defective recovery runtime."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from runtime.desktop_launch import (digest_json, inventory_tree, launch,
    _read_generations, plan_identity, runtime_migration_rule)
from tests import test_safe_updates as fixtures

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def proof(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('repair_fixture_proof', ROOT / 'scripts/test-onboarding-poc.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def case():
    value = fixtures.SafeUpdateTests(); value.setUp()
    try:yield value
    finally:value.doCleanups()


def original(case):
    bundle = case.root / 'original-bundle'
    shutil.copytree(case.old.parent / 'seed', bundle / 'prefix', symlinks=True)
    plan = json.loads(case.old.read_text())
    plan.update(state={'managerVersion': 1}, application={'name': 'proof', 'version': '1'})
    plan['target']['wine'] = 'unavailable-original-runtime-must-not-run'
    workflow = SimpleNamespace(app_id=plan['desktop']['id'], recovery_settings_fixture=lambda prefix:
        case.write(prefix, 'AppData/Roaming/Proof/settings', 'retained fixture settings'))
    return bundle, plan, workflow


def test_offline_original_fixture_repairs_with_real_manager_without_launching_original(proof, case, monkeypatch):
    bundle, source, workflow = original(case)
    before = inventory_tree(bundle / 'prefix')
    data = case.root / 'fresh-data'; state = data / source['desktop']['id']
    fixture = proof.prepare_repair_source_fixture(bundle, state, source, workflow)
    retained = state / 'prefix'
    case.write(retained, 'Documents/story.txt', 'current retained document')
    original_inventory = inventory_tree(retained, state_snapshot=True)
    assert fixture['identity'] == plan_identity(source)
    assert fixture['originalRuntimeExecuted'] is False

    repair = case.package('repaired')
    plan = json.loads(repair.read_text()); plan.update(state={'managerVersion': 1}, application=source['application'])
    seed = repair.parent / 'seed'
    (seed / 'drive_c/App.exe').write_text('1')
    (seed / 'drive_c/runtime.dll').write_text('guarded runtime seed')
    inventory = inventory_tree(seed); plan['seedDigest'] = digest_json(inventory)
    plan['desktop']['updates']['rollbackRepairs'] = [runtime_migration_rule(source, plan, repair=True)]
    repair.write_text(json.dumps(plan)); (repair.parent / 'seed-inventory.json').write_text(json.dumps(inventory))
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    assert launch(repair, ['--cage-rollback-repair']) == 0
    record = _read_generations(state); active = state / record['active']
    assert (active / 'drive_c/runtime.dll').read_text() == 'guarded runtime seed'
    assert case.read(active, 'AppData/Roaming/Proof/settings') == 'retained fixture settings'
    assert case.read(active, 'Documents/story.txt') == 'current retained document'
    assert inventory_tree(retained, state_snapshot=True) == original_inventory
    assert inventory_tree(bundle / 'prefix') == before
    assert launch(repair, []) == 0


def test_offline_fixture_refuses_changed_seed_before_creating_state(proof, case):
    bundle, plan, workflow = original(case)
    (bundle / 'prefix/drive_c/App.exe').write_text('changed')
    state = case.root / 'unused-state'
    with pytest.raises(RuntimeError, match='seed differs'):
        proof.prepare_repair_source_fixture(bundle, state, plan, workflow)
    assert not state.exists()


def test_offline_fixture_never_overwrites_existing_recovery_data(proof, case):
    bundle, plan, workflow = original(case); state = case.root / 'retained-state'
    proof.prepare_repair_source_fixture(bundle, state, plan, workflow)
    before = inventory_tree(state, state_snapshot=True)
    with pytest.raises(RuntimeError, match='existing state retained'):
        proof.prepare_repair_source_fixture(bundle, state, plan, workflow)
    assert inventory_tree(state, state_snapshot=True) == before


def test_offline_fixture_cannot_be_used_to_set_up_original_trusted_release():
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/test-onboarding-poc.py'),
        'appimage', 'original.AppImage', 'repair.AppImage', '--rollback-repair', '--trusted',
        '--qualification', 'repair.json', '--baseline-qualification', 'original.json',
        '--repair-source-bundle', 'producer'], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'cannot qualify an original signed release' in result.stderr
