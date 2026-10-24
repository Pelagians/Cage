"""Exercise state transactions through real subprocesses and on-disk generations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.manifest import load_manifest, ManifestError
from runtime.desktop_launch import (DesktopError, digest_json, inventory_tree, launch,
    lifecycle_lock, _read_generations, _generation, validate_update_policy, plan_identity,
    validate_runtime_update)
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
            'pending=out.with_suffix(".tmp")\n'
            'pending.write_text(json.dumps({"prefix":str(p),"pid":os.getpid(),"version":(p/"drive_c/App.exe").read_text()}))\n'
            'pending.replace(out)\n'
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

    def runtime_packages(self, **environment):
        old = json.loads(self.old.read_text())
        old.update(state={'managerVersion': 1}, application={'name': 'proof', 'version': '1'})
        self.old.write_text(json.dumps(old))
        # Exercise the supported v0 adoption before the runtime-only migration.
        self.assertEqual(launch(self.old, ['--cage-migrate']), 0)
        self.previous = self.active()
        self.initial = json.loads((self.state / 'state.json').read_text())
        candidate = self.package('runtime-candidate', **environment)
        plan = json.loads(candidate.read_text())
        plan.update(state={'managerVersion': 1}, application=old['application'])
        plan['target']['runtimeVersion'] = 'qualified-next'
        seed = candidate.parent / 'seed'
        (seed / 'drive_c/App.exe').write_text('1')
        (seed / 'drive_c/runtime.dll').write_text('new runtime system bytes')
        (seed / 'system.reg').write_text('new runtime hive')
        inventory = inventory_tree(seed)
        plan['seedDigest'] = digest_json(inventory)
        plan['desktop']['updates']['runtimeMigrations'] = [
            {'from': plan_identity(old), 'toRuntimeDigest': digest_json(plan['target'])}]
        candidate.write_text(json.dumps(plan))
        (candidate.parent / 'seed-inventory.json').write_text(json.dumps(inventory))
        return candidate

    def test_qualified_runtime_upgrade_uses_new_system_seed_and_retains_old_runtime_state(self):
        candidate = self.runtime_packages()
        (self.previous / 'drive_c/runtime.dll').write_text('old runtime system bytes')
        (self.previous / 'system.reg').write_text('old runtime hive')
        self.assertEqual(launch(candidate, ['--cage-update']), 0)
        updated = self.active()
        self.assertEqual((updated / 'drive_c/runtime.dll').read_text(), 'new runtime system bytes')
        self.assertEqual((updated / 'system.reg').read_text(), 'new runtime hive')
        self.assertEqual(self.read(updated, 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(self.read(updated, 'Documents/story.txt'), 'document v1')
        self.assertEqual((self.previous / 'drive_c/runtime.dll').read_text(), 'old runtime system bytes')
        self.assertEqual(launch(candidate, []), 0)
        self.write(updated, 'Documents/story.txt', 'newest document')
        self.write(updated, 'AppData/Roaming/Proof/settings', 'new runtime settings')
        with self.assertRaisesRegex(DesktopError, 'runtime changes'):
            launch(self.old, ['--cage-update'])
        self.assertEqual(launch(self.old, ['--cage-rollback']), 0)
        rolled = self.active()
        self.assertEqual((rolled / 'drive_c/runtime.dll').read_text(), 'old runtime system bytes')
        self.assertEqual((rolled / 'system.reg').read_text(), 'old runtime hive')
        self.assertEqual(self.read(rolled, 'Documents/story.txt'), 'newest document')
        self.assertEqual(self.read(rolled, 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(self.read(updated, 'AppData/Roaming/Proof/settings'), 'new runtime settings')
        self.assertEqual(launch(self.old, []), 0)
        self.assertEqual(self.external.read_text(), 'external document')
        self.assertTrue(any(g.get('runtimeMigration') for g in _read_generations(self.state)['generations']))

    def test_runtime_migration_is_exact_directed_and_keeps_application_bytes_fixed(self):
        candidate = self.runtime_packages()
        original = json.loads(candidate.read_text())
        changes = [('source contract', lambda p: p['desktop']['updates']['runtimeMigrations'][0]['from'].update(contractDigest='a'*64)),
                   ('target runtime', lambda p: p['desktop']['updates']['runtimeMigrations'][0].update(toRuntimeDigest='b'*64)),
                   ('application version', lambda p: p['application'].update(version='2')),
                   ('profile', lambda p: p['desktop']['updates'].update(profile='other/v1'))]
        for name, change in changes:
            with self.subTest(name=name):
                plan = json.loads(json.dumps(original)); change(plan); candidate.write_text(json.dumps(plan))
                with self.assertRaisesRegex(DesktopError, 'runtime changes'):
                    launch(candidate, ['--cage-update'])
                self.assertEqual(json.loads((self.state / 'state.json').read_text()), self.initial)
        candidate.write_text(json.dumps(original))
        executable = candidate.parent / 'seed/drive_c/App.exe'; executable.write_text('changed app')
        inventory = inventory_tree(candidate.parent / 'seed')
        original['seedDigest'] = digest_json(inventory)
        candidate.write_text(json.dumps(original))
        (candidate.parent / 'seed-inventory.json').write_text(json.dumps(inventory))
        with self.assertRaisesRegex(DesktopError, 'same pinned executable'):
            launch(candidate, ['--cage-update'])
        self.assertEqual(self.active(), self.previous)

    def test_runtime_migration_failure_and_interrupted_commit_keep_old_active(self):
        candidate = self.runtime_packages(PROOF_EXIT='7')
        self.assertEqual(launch(candidate, ['--cage-update']), 7)
        self.assertEqual(self.active(), self.previous)
        self.assertEqual(launch(self.old, []), 0)
        plan = json.loads(candidate.read_text()); plan['environment']['PROOF_EXIT'] = '0'
        candidate.write_text(json.dumps(plan))
        with patch('runtime.desktop_launch.commit_generation', side_effect=OSError('power loss')):
            with self.assertRaisesRegex(OSError, 'power loss'):
                launch(candidate, ['--cage-update'])
        self.assertEqual(self.active(), self.previous)
        self.assertEqual(launch(self.old, []), 0)
        self.assertEqual(launch(candidate, ['--cage-update']), 0)

    def test_runtime_migration_low_space_and_symlink_settings_refuse_without_commit(self):
        candidate = self.runtime_packages()
        with patch('runtime.desktop_launch.shutil.disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaisesRegex(DesktopError, 'insufficient space'):
                launch(candidate, ['--cage-update'])
        self.assertEqual(self.active(), self.previous)
        self.write(self.previous, 'AppData/Roaming/Proof/escape-placeholder', 'safe').unlink()
        (self.previous / 'drive_c/users/cage/AppData/Roaming/Proof/escape-placeholder').symlink_to(self.external)
        with self.assertRaisesRegex(DesktopError, 'ordinary files'):
            launch(candidate, ['--cage-update'])
        self.assertEqual(self.active(), self.previous)
        self.assertEqual(self.external.read_text(), 'external document')

    def test_runtime_preflight_rejects_changed_architecture_or_data_policy(self):
        candidate = self.runtime_packages()
        old = json.loads(self.old.read_text()); plan = json.loads(candidate.read_text())
        self.assertIsNotNone(validate_runtime_update(old, plan))
        for key, value in [('architecture', 'different'), ('graphics', 'wayland')]:
            with self.subTest(key=key):
                changed = json.loads(json.dumps(plan)); changed['target'][key] = value
                changed['desktop']['updates']['runtimeMigrations'][0]['toRuntimeDigest'] = digest_json(changed['target'])
                with self.assertRaisesRegex(DesktopError, 'architecture, adapter or data policy'):
                    validate_runtime_update(old, changed)
        plan['desktop']['updates']['settings'] = []
        with self.assertRaisesRegex(DesktopError, 'data policy'):
            validate_runtime_update(old, plan)

    def test_runtime_policy_rejects_unbound_legacy_duplicate_and_wildcard_transitions(self):
        candidate = self.runtime_packages()
        policy = json.loads(candidate.read_text())['desktop']['updates']
        validate_update_policy(policy)
        valid = policy['runtimeMigrations'][0]
        invalid = [[], [valid]*2, [valid]*17, [{'from': valid['from']}],
                   [{'from': {**valid['from'], 'schemaVersion': 'cage.desktop-state/v0'}, 'toRuntimeDigest': valid['toRuntimeDigest']}],
                   [{'from': {**valid['from'], 'contractDigest': '*'}, 'toRuntimeDigest': valid['toRuntimeDigest']}],
                   [{'from': valid['from'], 'toRuntimeDigest': valid['from']['runtimeDigest']}]]
        for migrations in invalid:
            with self.subTest(migrations=migrations):
                with self.assertRaises(DesktopError):validate_update_policy({**policy, 'runtimeMigrations': migrations})

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

    def test_standard_external_document_mapping_survives_update_and_rollback_without_traversal(self):
        home = self.root / 'host-home'
        documents = home / 'Documents'
        documents.mkdir(parents=True)
        external = documents / 'outside.txt'
        external.write_text('host document')
        external.chmod(0o444)
        relative = 'drive_c/users/another-login/Documents'
        mapped = self.previous / relative
        mapped.parent.mkdir(parents=True)
        mapped.symlink_to(documents)
        original_rglob = Path.rglob
        def no_mapping_traversal(path, *args, **kwargs):
            if path.is_symlink() and path.name == 'Documents':
                self.fail('external document mapping was traversed')
            return original_rglob(path, *args, **kwargs)
        with patch.dict(os.environ, {'HOME': str(home)}), patch.object(Path, 'rglob', no_mapping_traversal):
            self.assertEqual(launch(self.new, ['--cage-update']), 0)
            self.assertTrue((self.active() / relative).is_symlink())
            self.assertEqual(os.readlink(self.active() / relative), str(documents))
            self.assertEqual((self.active() / 'drive_c/App.exe').read_text(), '2')
            self.assertEqual(launch(self.old, ['--cage-rollback']), 0)
            self.assertEqual(os.readlink(self.active() / relative), str(documents))
            self.assertEqual((self.active() / 'drive_c/App.exe').read_text(), '1')
        self.assertEqual(external.read_text(), 'host document')
        self.assertEqual(external.stat().st_mode & 0o777, 0o444)
        self.assertEqual(os.readlink(mapped), str(documents))

    def test_arbitrary_relative_and_in_prefix_document_links_remain_refused(self):
        mapped = self.previous / 'drive_c/users/another-login/Documents'
        mapped.parent.mkdir(parents=True)
        for target in (str(self.root), '../cage/Documents', str(self.previous / 'drive_c')):
            with self.subTest(target=target):
                mapped.symlink_to(target)
                with self.assertRaisesRegex(DesktopError, 'document mapping'):
                    launch(self.new, ['--cage-update'])
                self.assertEqual(self.active(), self.previous)
                self.assertEqual(self.external.read_text(), 'external document')
                mapped.unlink()

    def test_settings_link_to_standard_document_folder_is_not_a_document_mapping(self):
        home = self.root / 'host-home'
        documents = home / 'Documents'
        documents.mkdir(parents=True)
        settings = self.previous / 'drive_c/users/cage/AppData/Roaming/Proof'
        settings.rename(settings.with_name('retained-settings'))
        settings.symlink_to(documents)
        with patch.dict(os.environ, {'HOME': str(home)}), self.assertRaisesRegex(DesktopError, 'linked'):
            launch(self.new, ['--cage-update'])
        self.assertEqual(self.active(), self.previous)
        self.assertEqual(list(documents.iterdir()), [])

    def test_rollback_rejects_changed_destination_document_mapping(self):
        home = self.root / 'host-home'
        documents = home / 'Documents'
        documents.mkdir(parents=True)
        relative = 'drive_c/users/another-login/Documents'
        mapped = self.previous / relative
        mapped.parent.mkdir(parents=True)
        mapped.symlink_to(documents)
        with patch.dict(os.environ, {'HOME': str(home)}):
            self.assertEqual(launch(self.new, ['--cage-update']), 0)
            current = self.active()
            mapped.unlink()
            mapped.symlink_to(self.root)
            with self.assertRaisesRegex(DesktopError, 'document mapping'):
                launch(self.old, ['--cage-rollback'])
            self.assertEqual(self.active(), current)
            self.assertEqual((current / 'drive_c/App.exe').read_text(), '2')

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

    def test_clean_exit_releases_lock_even_when_a_detached_helper_inherited_it(self):
        import signal
        import subprocess
        import sys
        info = self.root / 'detached-pid'
        child = None
        try:
            with lifecycle_lock(self.state) as descriptor:
                subprocess.run([sys.executable, '-c',
                    'import subprocess,sys; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],pass_fds=(int(sys.argv[1]),));open(sys.argv[2],"w").write(str(p.pid))',
                    str(descriptor), str(info)], pass_fds=(descriptor,), check=True)
                child = int(info.read_text())
            os.kill(child, 0)
            with lifecycle_lock(self.state):
                pass
        finally:
            if child is not None:
                os.kill(child, signal.SIGKILL)

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
        interrupted = retained.parent / 'interrupted.partial'
        interrupted.write_bytes(b'partial update retained')
        with self.assertRaisesRegex(DesktopError, 'untracked update files'):
            integration.integrate(appdir, plan, remove=True)
        self.assertTrue(retained.exists())
        self.assertTrue(stable.exists())
        interrupted.unlink()
        retained.write_bytes(b'changed')
        with self.assertRaisesRegex(DesktopError, 'changed'):
            integration.integrate(appdir, plan, remove=True)
        self.assertTrue(stable.exists())


if __name__ == '__main__':
    unittest.main()
