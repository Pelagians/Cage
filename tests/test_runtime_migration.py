"""Producer declarations and the real container process wrapper share policy."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.manifest import load_manifest
from runtime.container_state import run
from runtime.desktop_launch import DesktopError, _read_generations, plan_identity
from tests import test_safe_updates as fixtures

ROOT = Path(__file__).resolve().parents[1]
prepare = runpy.run_path(str(ROOT / 'scripts/prepare-runtime-migration-poc.py'))['prepare']


class RuntimeRecipeTests(unittest.TestCase):
    def test_one_recipe_binds_multiple_adapters_without_claiming_qualification(self):
        recipe = ROOT / 'recipes/sumatrapdf-portable.cage.yaml'
        manifest = load_manifest(recipe)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); pairs = []
            for kind in ('flatpak', 'appimage'):
                previous = {'format': kind, 'desktop': manifest.desktop, 'state': {'managerVersion': 1},
                            'application': {'name': manifest.name, 'version': manifest.version},
                            'seedDigest': 'a'*64, 'target': {'architecture': 'x86_64', 'provider': 'wine', 'revision': 'old'}}
                candidate = json.loads(json.dumps(previous)); candidate['target']['revision'] = 'new'
                paths = [root / (kind + '-' + name + '.json') for name in ('old', 'new')]
                paths[0].write_text(json.dumps({'plan': previous})); paths[1].write_text(json.dumps(candidate))
                pairs.append(paths)
            output = root / 'recipe.json'
            command = [sys.executable, str(ROOT / 'scripts/prepare-runtime-migration-poc.py'), str(recipe)]
            for pair in pairs:command.extend(['--pair', *map(str, pair)])
            result = json.loads(subprocess.check_output([*command, '--output', str(output)], text=True))
            self.assertEqual(len(result['runtimeMigrations']), 2)
            self.assertIn('proposal only', result['qualification'])
            updated = load_manifest(output)
            self.assertEqual(updated.modules, manifest.modules)
            self.assertEqual(updated.runtime, manifest.runtime)
            self.assertEqual(updated.desktop['updates']['settings'], manifest.desktop['updates']['settings'])
            self.assertFalse('runtimeMigrations' in manifest.desktop['updates'])
            repair_output=root/'repair.json'
            repair=json.loads(subprocess.check_output([*command,'--rollback-repair','--output',str(repair_output)],text=True))
            self.assertEqual(len(repair['rollbackRepairs']),2)
            self.assertNotIn('runtimeMigrations',load_manifest(repair_output).desktop['updates'])
            with self.assertRaises(FileExistsError):prepare(recipe, pairs, output)
            changed = json.loads(paths[1].read_text()); changed['application']['version'] = 'other'
            paths[1].write_text(json.dumps(changed))
            with self.assertRaisesRegex(DesktopError, 'application/data policy'):
                prepare(recipe, pairs, root / 'invalid.json')


class ContainerRuntimeMigrationTests(unittest.TestCase):
    setUp = fixtures.SafeUpdateTests.setUp
    package = fixtures.SafeUpdateTests.package
    write = fixtures.SafeUpdateTests.write
    read = fixtures.SafeUpdateTests.read
    active = fixtures.SafeUpdateTests.active
    runtime_packages = fixtures.SafeUpdateTests.runtime_packages

    def test_real_container_wrapper_accepts_explicit_repair_without_replacing_original(self):
        candidate=self.runtime_packages();plan=json.loads(candidate.read_text())
        policy=plan['desktop']['updates'];policy['rollbackRepairs']=policy.pop('runtimeMigrations')
        (candidate.parent/'seed').rename(candidate.parent/'prefix')
        script='exec '+str(self.runtime/'wine')+' C:/App.exe'
        with patch.dict(os.environ,{'CAGE_BUNDLE':str(candidate.parent),'CAGE_STATE':str(self.data),
                                   'PROOF_LOG':str(self.root/'container-proof.json'),
                                   'PATH':str(self.runtime)+os.pathsep+os.environ['PATH']}):
            self.assertEqual(run(plan,script,['--cage-rollback-repair']),0)
        record=_read_generations(self.state)
        active=next(g for g in record['generations'] if g['prefix']==record['active'])
        self.assertEqual(active['rollbackRepair']['from'],plan_identity(json.loads(self.old.read_text())))
        self.assertEqual((self.active()/'drive_c/runtime.dll').read_text(),'new runtime system bytes')
        self.assertEqual(self.read(self.previous,'AppData/Roaming/Proof/settings'),'my settings')

    def test_real_process_wrapper_migrates_and_rolls_back_without_replacing_existing_state(self):
        candidate = self.runtime_packages()
        candidate_plan = json.loads(candidate.read_text())
        (candidate.parent / 'seed').rename(candidate.parent / 'prefix')
        script = 'exec ' + str(self.runtime / 'wine') + ' C:/App.exe'
        environment = {'CAGE_BUNDLE': str(candidate.parent), 'CAGE_STATE': str(self.data),
                       'PROOF_LOG': str(self.root / 'container-proof.json'),
                       'PATH': str(self.runtime) + os.pathsep + os.environ['PATH']}
        with patch.dict(os.environ, environment):
            self.assertEqual(run(candidate_plan, script, ['--cage-update']), 0)
            updated = self.active()
            self.assertEqual(run(candidate_plan, script, []), 0)
            self.assertEqual(self.read(updated, 'AppData/Roaming/Proof/settings'), 'my settings')
            self.write(updated, 'Documents/story.txt', 'latest container document')
            self.write(updated, 'AppData/Roaming/Proof/settings', 'new runtime settings')
            old_plan = json.loads(self.old.read_text())
            (self.old.parent / 'seed').rename(self.old.parent / 'prefix')
            with patch.dict(os.environ, {'CAGE_BUNDLE': str(self.old.parent)}):
                self.assertEqual(run(old_plan, script, ['--cage-rollback']), 0)
                self.assertEqual(run(old_plan, script, []), 0)
        self.assertEqual(self.read(self.active(), 'Documents/story.txt'), 'latest container document')
        self.assertEqual(self.read(self.active(), 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(self.read(updated, 'AppData/Roaming/Proof/settings'), 'new runtime settings')
        self.assertEqual(self.external.read_text(), 'external document')
        record = _read_generations(self.state)
        self.assertTrue(any(g['identity'] == plan_identity(candidate_plan) for g in record['generations']))
