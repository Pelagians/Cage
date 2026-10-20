"""Exercise state transactions through real subprocesses and on-disk generations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.manifest import load_manifest, ManifestError
from runtime.desktop_launch import (DesktopError, digest_json, inventory_tree, launch,
    lifecycle_lock, _read_generations, _generation, validate_update_policy)
from tests.test_appimage_export import integration

APP = 'org.example.UpdateProof'
POLICY = {'profile': 'update-proof/v1',
          'settings': ['drive_c/users/*/AppData/Roaming/Proof'],
          'documents': ['drive_c/users/*/Documents']}


class SafeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        wine = self.runtime / 'wine'
        wine.write_text('#!/usr/bin/python3\nimport os,json,pathlib,sys\n'
            'p=pathlib.Path(os.environ["WINEPREFIX"])\n'
            'out=pathlib.Path(os.environ["PROOF_LOG"])\n'
            'out.write_text(json.dumps({"prefix":str(p),"pid":os.getpid(),"version":(p/"drive_c/App.exe").read_text()}))\n'
            'if os.environ.get("PROOF_WAIT"): __import__("time").sleep(60)\n'
            'sys.exit(int(os.environ.get("PROOF_EXIT","0")))\n')
        wine.chmod(0o755)
        server = self.runtime / 'wineserver'
        server.write_text('#!/bin/sh\nexit "${PROOF_SERVER_EXIT:-0}"\n')
        server.chmod(0o755)
        self.data = self.root / 'data'
        self.state = self.data / APP
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.data)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.old = self.package('1')
        self.new = self.package('2')
        self.assertEqual(launch(self.old, []), 0)
        self.initial = json.loads((self.state / 'state.json').read_text())
        self.previous = self.state / 'prefix'
        self.write(self.previous, 'AppData/Roaming/Proof/settings', 'my settings')
        self.write(self.previous, 'Documents/story.txt', 'document v1')
        self.external = self.root / 'outside.txt'
        self.external.write_text('external document')

    def package(self, version, **environment):
        package = self.root / ('package-' + version)
        seed = package / 'seed'
        (seed / 'drive_c').mkdir(parents=True)
        (seed / 'drive_c/App.exe').write_text(version)
        (seed / 'dosdevices').mkdir()
        (seed / 'dosdevices/c:').symlink_to('../drive_c')
        self.write(seed, 'AppData/Roaming/Proof/settings', 'default ' + version)
        self.write(seed, 'Documents/default.txt', 'default')
        inventory = inventory_tree(seed)
        plan = {'desktop': {'id': APP, 'updates': POLICY}, 'application': {'version': version},
                'target': {'wine': 'wine', 'wineserver': 'wineserver', 'graphics': 'x11'},
                'layout': {'runtime': str(self.runtime)}, 'seedDigest': digest_json(inventory),
                'environment': {'PROOF_LOG': str(self.root / 'proof.json'), **environment},
                'launch': {'entrypoint': 'C:/App.exe'}}
        (package / 'desktop.json').write_text(json.dumps(plan))
        (package / 'seed-inventory.json').write_text(json.dumps(inventory))
        return package / 'desktop.json'

    def write(self, prefix, relative, text):
        path = prefix / 'drive_c/users/cage' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def read(self, prefix, relative):
        return (prefix / 'drive_c/users/cage' / relative).read_text()

    def active(self):
        record = _read_generations(self.state)
        return self.state / record['active']

    def test_update_launches_new_bytes_preserves_settings_and_rollback_keeps_new_documents(self):
        self.assertEqual(launch(self.new, ['--cage-update', str(self.external)]), 0)
        current = self.active()
        self.assertNotEqual(current, self.previous)
        self.assertEqual(json.loads((self.root / 'proof.json').read_text())['version'], '2')
        self.assertEqual(self.read(current, 'AppData/Roaming/Proof/settings'), 'my settings')
        self.write(current, 'AppData/Roaming/Proof/settings', 'updated settings')
        self.write(current, 'Documents/story.txt', 'latest document')
        self.write(current, 'Documents/added.txt', 'created after update')
        self.assertEqual(launch(self.new, []), 0)
        with self.assertRaisesRegex(DesktopError, 'different seed/runtime'):
            launch(self.old, [])
        self.assertEqual(launch(self.old, ['--cage-rollback']), 0)
        rolled_back = self.active()
        self.assertEqual(json.loads((self.root / 'proof.json').read_text())['version'], '1')
        self.assertEqual(self.read(rolled_back, 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(self.read(rolled_back, 'Documents/story.txt'), 'latest document')
        self.assertEqual(self.read(rolled_back, 'Documents/added.txt'), 'created after update')
        self.assertEqual(self.read(current, 'AppData/Roaming/Proof/settings'), 'updated settings')
        self.assertEqual(self.read(self.previous, 'Documents/story.txt'), 'document v1')
        self.assertEqual(self.external.read_text(), 'external document')
        self.assertEqual(launch(self.old, []), 0)

    def test_nonzero_trial_retains_candidate_and_old_active_prefix(self):
        failed = self.package('bad', PROOF_EXIT='7')
        self.assertEqual(launch(failed, ['--cage-update']), 7)
        self.assertEqual(self.active(), self.previous)
        self.assertEqual(launch(self.old, []), 0)
        candidates = list((self.state / 'generations').iterdir())
        self.assertEqual(len(candidates), 1)
        self.assertEqual(self.read(candidates[0], 'Documents/story.txt'), 'document v1')
        self.assertEqual(json.loads((self.state / 'state.json').read_text()), self.initial)

    def test_cleanup_failure_cannot_commit(self):
        failed = self.package('cleanup-failure', PROOF_SERVER_EXIT='1')
        import subprocess
        with self.assertRaises(subprocess.CalledProcessError):
            launch(failed, ['--cage-update'])
        self.assertEqual(self.active(), self.previous)

    def test_failed_migration_and_interrupted_commit_leave_old_state_relaunchable(self):
        with patch('runtime.desktop_launch._migrate_paths', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                launch(self.new, ['--cage-update'])
        self.assertEqual(launch(self.old, []), 0)
        with patch('runtime.desktop_launch.commit_generation', side_effect=OSError('interrupted')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                launch(self.new, ['--cage-update'])
        self.assertEqual(launch(self.old, []), 0)
        self.assertEqual(launch(self.new, ['--cage-update']), 0)
        self.assertEqual(len(list((self.state / 'generations').iterdir())), 3)

    def test_runtime_mismatch_and_wrong_package_rollback_fail_closed(self):
        changed = self.package('runtime-change')
        plan = json.loads(changed.read_text())
        plan['target']['runtimeVersion'] = 'unqualified'
        changed.write_text(json.dumps(plan))
        with self.assertRaisesRegex(DesktopError, 'runtime changes'):
            launch(changed, ['--cage-update'])
        self.assertEqual(launch(self.new, ['--cage-update']), 0)
        with self.assertRaisesRegex(DesktopError, 'previous package/runtime'):
            launch(self.new, ['--cage-rollback'])
        self.assertEqual((self.active() / 'drive_c/App.exe').read_text(), '2')

    def test_links_fifo_and_symlinked_generation_are_rejected_without_touching_external_data(self):
        path = self.previous / 'drive_c/users/cage/AppData/Roaming/Proof/escape'
        path.symlink_to(self.external)
        with self.assertRaisesRegex(DesktopError, 'ordinary files'):
            launch(self.new, ['--cage-update'])
        self.assertEqual(self.external.read_text(), 'external document')
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(DesktopError):
            launch(self.new, ['--cage-update'])
        path.unlink()
        (self.state / 'generations').rename(self.state / 'retained')
        (self.state / 'generations').symlink_to(self.root)
        with self.assertRaisesRegex(DesktopError, 'linked'):
            launch(self.new, ['--cage-update'])

    def test_running_application_prevents_update_and_rollback(self):
        with lifecycle_lock(self.state):
            for metadata, args in [(self.old, []), (self.new, ['--cage-update']), (self.old, ['--cage-rollback'])]:
                with self.assertRaisesRegex(DesktopError, 'already running'):
                    launch(metadata, args)
        self.assertFalse((self.state / 'generations').exists())

    def test_opt_in_policy_is_required(self):
        plan = json.loads(self.new.read_text())
        del plan['desktop']['updates']
        self.new.write_text(json.dumps(plan))
        with self.assertRaisesRegex(DesktopError, 'no qualified update policy'):
            launch(self.new, ['--cage-update'])

    def test_bad_policy_paths_are_rejected(self):
        for value in ['../user.reg', 'drive_c/Program Files', 'drive_c/users/*/../../outside',
                      'drive_c/users/*/AppData', 'drive_c/users/*/AppData/Roaming/*']:
            with self.subTest(value=value), self.assertRaises(DesktopError):
                validate_update_policy({**POLICY, 'settings': [value]})
        with self.assertRaisesRegex(DesktopError, 'overlapping'):
            validate_update_policy({**POLICY, 'settings': [*POLICY['settings'], POLICY['settings'][0] + '/more']})

    def test_contract_only_update_and_legacy_state_adoption(self):
        from runtime.desktop_launch import plan_identity
        plan = json.loads(self.old.read_text())
        plan['state'] = {'managerVersion': 1, 'launcherSha256': 'baseline'}
        metadata = self.old.parent / 'contract.json'
        metadata.write_text(json.dumps(plan))
        self.assertEqual(launch(metadata, ['--cage-update']), 0)
        first = self.active()
        self.assertEqual(_generation(_read_generations(self.state), _read_generations(self.state)['active'])['identity'], plan_identity(plan))
        plan['state']['launcherSha256'] = 'patched launcher'
        patched = self.old.parent / 'patched.json'
        patched.write_text(json.dumps(plan))
        self.assertEqual(launch(patched, ['--cage-update']), 0)
        self.assertNotEqual(self.active(), first)
        self.assertEqual(self.read(self.active(), 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(launch(metadata, ['--cage-rollback']), 0)

    def test_rollback_does_not_resurrect_deleted_documents(self):
        self.assertEqual(launch(self.new, ['--cage-update']), 0)
        import shutil
        shutil.rmtree(self.active() / 'drive_c/users/cage/Documents')
        self.assertEqual(launch(self.old, ['--cage-rollback']), 0)
        self.assertFalse((self.active() / 'drive_c/users/cage/Documents').exists())
        self.assertTrue((self.previous / 'drive_c/users/cage/Documents/story.txt').exists())

    def test_orphan_wine_service_blocks_migration_before_copy(self):
        import subprocess
        from runtime.desktop_launch import assert_quiescent
        with patch('runtime.desktop_launch.subprocess.run', side_effect=subprocess.TimeoutExpired('wineserver', 1)):
            with self.assertRaisesRegex(DesktopError, 'Wine is still running'):
                launch(self.new, ['--cage-update'])
        self.assertFalse((self.state / 'generations').exists())

    def test_killed_launcher_cannot_release_a_running_app_lifecycle_lock(self):
        import signal
        import subprocess
        import sys
        import time
        package = self.package('crash', PROOF_WAIT='1')
        process = subprocess.Popen([sys.executable, '-c',
            'import sys; from runtime.desktop_launch import launch; sys.exit(launch(sys.argv[1], ["--cage-update"]))',
            str(package)], cwd=Path(__file__).resolve().parents[1])
        child = None
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                info = json.loads((self.root / 'proof.json').read_text())
                if info['version'] == 'crash':
                    child = info['pid']
                    break
                time.sleep(0.02)
            self.assertIsNotNone(child, 'trial application never started')
            process.kill()
            process.wait(timeout=5)
            with self.assertRaisesRegex(DesktopError, 'already running'):
                launch(self.old, [])
            os.kill(child, signal.SIGKILL)
            child = None
            deadline = time.monotonic() + 5
            while True:
                try:
                    with lifecycle_lock(self.state):
                        break
                except DesktopError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.02)
            self.assertEqual(launch(self.old, []), 0)
            self.assertEqual(self.active(), self.previous)
        finally:
            if child is not None:
                os.kill(child, signal.SIGKILL)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_first_generation_records_profile_and_refuses_incompatible_upgrade(self):
        from runtime.desktop_launch import plan_identity
        plan = json.loads(self.old.read_text())
        plan['state'] = {'managerVersion': 1}
        metadata = self.old.parent / 'managed.json'
        metadata.write_text(json.dumps(plan))
        # Start fresh using the generation-aware baseline, not a legacy record.
        import shutil
        shutil.rmtree(self.state)
        self.assertEqual(launch(metadata, []), 0)
        current = _generation(_read_generations(self.state), 'prefix')
        self.assertEqual(current['profile'], POLICY['profile'])
        candidate = json.loads(self.new.read_text())
        candidate['desktop']['updates']['profile'] = 'incompatible/v2'
        candidate['state'] = {'managerVersion': 1}
        self.new.write_text(json.dumps(candidate))
        with self.assertRaisesRegex(DesktopError, 'incompatible update profiles'):
            launch(self.new, ['--cage-update'])
        self.assertEqual(self.active(), self.state / 'prefix')

    def test_appimage_retains_exact_candidate_before_state_activation(self):
        plan = json.loads(self.old.read_text())
        plan['desktop'].update(name='Proof', summary='Proof', categories=['Utility'])
        appdir = self.root / 'AppDir'
        appdir.mkdir()
        (appdir / (APP + '.svg')).write_text('<svg/>')
        source = self.root / 'old.AppImage'
        source.write_bytes(b'\x7fELFold')
        with patch.dict(os.environ, {'APPIMAGE': str(source)}):
            installed = integration.integrate(appdir, plan)
        candidate = self.root / 'new.AppImage'
        candidate.write_bytes(b'\x7fELFnew')
        new_plan = json.loads(self.new.read_text())
        with patch.dict(os.environ, {'APPIMAGE': str(candidate)}):
            integration.stage_update(new_plan)
        stable = Path(installed['installed'])
        self.assertEqual(stable.read_bytes(), source.read_bytes())
        receipt = json.loads((stable.parent / 'installation.json').read_text())
        entry = receipt['versions'][0]
        retained = stable.parent / entry['package']
        self.assertEqual(retained.read_bytes(), candidate.read_bytes())
        retained.write_bytes(b'changed')
        with self.assertRaisesRegex(DesktopError, 'changed'):
            integration.integrate(appdir, plan, remove=True)
        self.assertTrue(stable.exists())


if __name__ == '__main__':
    unittest.main()
