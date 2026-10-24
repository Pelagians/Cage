"""An explicit repair restores old settings without executing the broken runtime."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runtime.desktop_launch import (DesktopError, _read_generations, launch,
    digest_json, plan_identity, validate_runtime_update)
from tests import test_safe_updates as fixtures


class RollbackRepairTests(unittest.TestCase):
    setUp = fixtures.SafeUpdateTests.setUp
    package = fixtures.SafeUpdateTests.package
    write = fixtures.SafeUpdateTests.write
    read = fixtures.SafeUpdateTests.read
    active = fixtures.SafeUpdateTests.active
    runtime_packages = fixtures.SafeUpdateTests.runtime_packages

    def repair(self, *, updated=False, **environment):
        candidate = self.runtime_packages(**environment)
        if updated:
            self.assertEqual(launch(candidate, ['--cage-update']), 0)
        plan = json.loads(candidate.read_text())
        plan['desktop']['updates']['rollbackRepairs'] = plan['desktop']['updates'].pop('runtimeMigrations')
        candidate.write_text(json.dumps(plan))
        return candidate

    def test_repair_uses_fresh_system_files_old_settings_latest_documents_and_real_identity(self):
        repair = self.repair(updated=True)
        current = self.active()
        self.write(current, 'Documents/story.txt', 'latest after upgrade')
        self.write(current, 'AppData/Roaming/Proof/settings', 'new settings retained')
        (self.previous / 'drive_c/runtime.dll').write_text('broken runtime')
        (self.previous / 'system.reg').write_text('old registry')
        original = {p.relative_to(self.previous): p.read_bytes() for p in self.previous.rglob('*') if p.is_file() and not p.is_symlink()}
        self.assertEqual(launch(repair, ['--cage-rollback-repair']), 0)
        restored = self.active()
        self.assertEqual(self.read(restored, 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(self.read(restored, 'Documents/story.txt'), 'latest after upgrade')
        self.assertEqual((restored / 'drive_c/runtime.dll').read_text(), 'new runtime system bytes')
        self.assertEqual((restored / 'system.reg').read_text(), 'new runtime hive')
        self.assertEqual(self.read(current, 'AppData/Roaming/Proof/settings'), 'new settings retained')
        for relative, data in original.items():
            self.assertEqual((self.previous / relative).read_bytes(), data)
        state = _read_generations(self.state)
        entry = next(g for g in state['generations'] if g['prefix'] == state['active'])
        self.assertEqual(entry['identity'], plan_identity(json.loads(repair.read_text())))
        self.assertEqual(entry['rollbackRepair'], {'source': str(self.previous.relative_to(self.state)),
            'from': plan_identity(json.loads(self.old.read_text())), 'to': entry['identity']})
        self.assertNotIn('runtimeMigration', entry)
        self.assertEqual(launch(repair, []), 0)
        self.assertEqual(self.active(), restored)
        self.assertEqual(self.external.read_text(), 'external document')

    def test_active_original_can_be_repaired_after_an_already_completed_rollback(self):
        repair = self.repair(updated=True)
        self.assertEqual(launch(self.old, ['--cage-rollback']), 0)
        rolled = self.active()
        self.assertEqual(launch(repair, ['--cage-rollback-repair']), 0)
        restored = self.active()
        record = _read_generations(self.state)
        entry = next(g for g in record['generations'] if g['prefix'] == record['active'])
        self.assertEqual(entry['rollbackRepair']['source'],str(rolled.relative_to(self.state)))
        self.assertEqual(self.read(restored, 'AppData/Roaming/Proof/settings'), 'my settings')
        # Repeating explicitly restores the retained original's settings again,
        # without selecting the original runtime or relabelling its prefix.
        self.write(restored, 'AppData/Roaming/Proof/settings', 'changed after repair')
        self.write(restored, 'Documents/story.txt', 'new document after repair')
        self.assertEqual(launch(repair, ['--cage-rollback-repair']), 0)
        self.assertEqual(self.read(self.active(), 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(self.read(self.active(), 'Documents/story.txt'), 'new document after repair')

    def test_repair_rule_does_not_authorize_an_ordinary_upgrade_or_unlisted_source(self):
        repair = self.repair()
        before = (self.state / 'state.json').read_bytes()
        with self.assertRaisesRegex(DesktopError, 'runtime changes'):
            launch(repair, ['--cage-update'])
        plan = json.loads(repair.read_text())
        plan['desktop']['updates']['rollbackRepairs'][0]['from']['contractDigest'] = 'a'*64
        repair.write_text(json.dumps(plan))
        with self.assertRaisesRegex(DesktopError, 'no exact qualified rollback repair'):
            launch(repair, ['--cage-rollback-repair'])
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_failed_trial_and_interrupted_commit_retain_active_and_candidates(self):
        repair = self.repair(PROOF_EXIT='7')
        before = (self.state / 'state.json').read_bytes()
        self.assertEqual(launch(repair, ['--cage-rollback-repair']), 7)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)
        plan = json.loads(repair.read_text()); plan['environment']['PROOF_EXIT'] = '0'
        repair.write_text(json.dumps(plan))
        with patch('runtime.desktop_launch.commit_generation', side_effect=OSError('power loss')):
            with self.assertRaisesRegex(OSError, 'power loss'):
                launch(repair, ['--cage-rollback-repair'])
        self.assertEqual((self.state / 'state.json').read_bytes(), before)
        self.assertGreaterEqual(len(list((self.state / 'generations').iterdir())), 3)

    def test_repair_preflight_rejects_application_abi_and_data_policy_changes(self):
        repair = self.repair()
        old = json.loads(self.old.read_text()); valid = json.loads(repair.read_text())
        self.assertIsNotNone(validate_runtime_update(old, valid, repair=True))
        for field, value in [('architecture', 'foreign'), ('graphics', 'wayland')]:
            plan = json.loads(json.dumps(valid)); plan['target'][field] = value
            plan['desktop']['updates']['rollbackRepairs'][0]['toRuntimeDigest'] = digest_json(plan['target'])
            with self.subTest(field=field), self.assertRaisesRegex(DesktopError, 'architecture, adapter or data policy'):
                validate_runtime_update(old, plan, repair=True)
        for change in (lambda p: p['application'].update(version='different'),
                       lambda p: p['desktop']['updates'].update(documents=['drive_c/users/*/Desktop'])):
            plan = json.loads(json.dumps(valid)); change(plan)
            with self.assertRaises(DesktopError):
                validate_runtime_update(old, plan, repair=True)

    def test_low_storage_and_unsafe_settings_leave_original_active(self):
        repair=self.repair();before=(self.state/'state.json').read_bytes()
        with patch('runtime.desktop_launch.shutil.disk_usage',return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(DesktopError,'space'):
                launch(repair,['--cage-rollback-repair'])
        self.assertEqual((self.state/'state.json').read_bytes(),before)
        settings=self.previous/'drive_c/users/cage/AppData/Roaming/Proof/settings'
        settings.unlink();settings.symlink_to(self.external)
        with self.assertRaisesRegex(DesktopError,'ordinary'):
            launch(repair,['--cage-rollback-repair'])
        self.assertEqual(self.external.read_text(),'external document')
        self.assertEqual((self.state/'state.json').read_bytes(),before)

    def test_runtime_migration_permission_alone_cannot_authorize_repair(self):
        candidate=self.runtime_packages();before=(self.state/'state.json').read_bytes()
        with self.assertRaisesRegex(DesktopError,'no exact qualified rollback repair'):
            launch(candidate,['--cage-rollback-repair'])
        self.assertEqual((self.state/'state.json').read_bytes(),before)

    def test_repair_verifies_the_retained_source_executable_not_the_current_one(self):
        repair=self.repair(updated=True);before=(self.state/'state.json').read_bytes()
        (self.previous/'drive_c/App.exe').write_text('altered retained application')
        with self.assertRaisesRegex(DesktopError,'same pinned executable'):
            launch(repair,['--cage-rollback-repair'])
        self.assertEqual((self.state/'state.json').read_bytes(),before)
