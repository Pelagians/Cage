"""Legacy adoption keeps source bytes, failed work and exact package recovery."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from runtime.desktop_launch import (DesktopError, inventory_tree, launch, plan_identity,
                                    _read_generations, _generation)
from tests import test_safe_updates as fixtures
from tests.test_appimage_export import integration
from core.sources import prepare_portable_source
from core.manifest import Manifest
from core.media import MediaStageError


class LegacyMigrationTests(unittest.TestCase):
    setUp = fixtures.SafeUpdateTests.setUp
    package = fixtures.SafeUpdateTests.package
    write = fixtures.SafeUpdateTests.write
    read = fixtures.SafeUpdateTests.read
    active = fixtures.SafeUpdateTests.active

    def baseline(self):
        plan = json.loads(self.old.read_text())
        plan['state'] = {'managerVersion': 1}
        metadata = self.old.parent / 'managed.json'
        metadata.write_text(json.dumps(plan))
        return metadata

    def test_snapshot_adoption_then_update_and_rollback_preserve_all_user_state(self):
        baseline = self.baseline()
        original = inventory_tree(self.previous, state_snapshot=True)
        self.assertEqual(launch(baseline, ['--cage-migrate']), 0)
        journal = json.loads((self.state / 'legacy-migration.json').read_text())
        snapshot = self.state / journal['snapshot']
        self.assertEqual(inventory_tree(snapshot / 'prefix', state_snapshot=True), original)
        self.assertEqual(inventory_tree(self.previous, state_snapshot=True), original)
        self.assertEqual(json.loads((snapshot / 'state.json').read_text()), self.initial)
        # Literal external Wine drive links in a recovery snapshot cannot be
        # admitted as an export payload inventory.
        with self.assertRaisesRegex(DesktopError, 'escaping'):
            inventory_tree(snapshot / 'prefix')
        plan = json.loads(self.new.read_text()); plan['state'] = {'managerVersion': 1}
        self.new.write_text(json.dumps(plan))
        self.assertEqual(launch(self.new, ['--cage-update']), 0)
        self.write(self.active(), 'Documents/story.txt', 'latest work')
        self.assertEqual(launch(baseline, ['--cage-rollback']), 0)
        self.assertEqual(self.read(self.active(), 'Documents/story.txt'), 'latest work')
        self.assertEqual(self.read(self.active(), 'AppData/Roaming/Proof/settings'), 'my settings')
        self.assertEqual(inventory_tree(snapshot / 'prefix', state_snapshot=True), original)

    def test_existing_explicit_update_also_snapshots_legacy_state(self):
        self.assertEqual(launch(self.baseline(), ['--cage-update']), 0)
        self.assertTrue((self.state / 'legacy-migration.json').is_file())

    def test_explicit_adoption_requires_the_pinned_baseline_before_a_version_update(self):
        plan = json.loads(self.new.read_text()); plan['state'] = {'managerVersion': 1}
        self.new.write_text(json.dumps(plan))
        before = inventory_tree(self.previous, state_snapshot=True)
        with self.assertRaisesRegex(DesktopError, 'same pinned application executable'):
            launch(self.new, ['--cage-migrate'])
        self.assertEqual(inventory_tree(self.previous, state_snapshot=True), before)
        self.assertFalse((self.state / 'legacy-snapshots').exists())
        self.assertFalse((self.state / 'generations').exists())

    def test_low_space_and_runtime_change_leave_original_pointer_and_bytes(self):
        baseline = self.baseline()
        before = inventory_tree(self.previous, state_snapshot=True)
        with patch('runtime.desktop_launch.shutil.disk_usage', return_value=shutil._ntuple_diskusage(1, 1, 0)):
            with self.assertRaisesRegex(DesktopError, 'insufficient space'):
                launch(baseline, ['--cage-migrate'])
        self.assertFalse((self.state / 'generations').exists())
        plan = json.loads(baseline.read_text()); plan['target']['version'] = 'other'
        baseline.write_text(json.dumps(plan))
        with self.assertRaisesRegex(DesktopError, 'runtime changes'):
            launch(baseline, ['--cage-migrate'])
        self.assertEqual(json.loads((self.state / 'state.json').read_text()), self.initial)
        self.assertEqual(inventory_tree(self.previous, state_snapshot=True), before)

    def test_failed_trial_retains_snapshot_candidate_and_original(self):
        baseline = self.baseline(); plan = json.loads(baseline.read_text())
        plan['environment']['PROOF_EXIT'] = '9'; baseline.write_text(json.dumps(plan))
        self.assertEqual(launch(baseline, ['--cage-migrate']), 9)
        self.assertEqual(self.active(), self.previous)
        self.assertEqual(len(list((self.state / 'generations').iterdir())), 1)
        self.assertEqual(len(list((self.state / 'legacy-snapshots').iterdir())), 1)
        self.assertEqual(launch(self.old, []), 0)

    def test_no_state_is_not_an_import_and_managed_state_is_not_relabelled(self):
        baseline = self.baseline()
        shutil.rmtree(self.state)
        with self.assertRaisesRegex(DesktopError, 'existing recorded legacy'):
            launch(baseline, ['--cage-migrate'])
        self.assertFalse((self.state / 'prefix').exists())
        self.assertEqual(launch(baseline, []), 0)
        with self.assertRaisesRegex(DesktopError, 'recorded v0'):
            launch(baseline, ['--cage-migrate'])


class AppImageMigrationTests(unittest.TestCase):
    package = fixtures.SafeUpdateTests.package
    write = fixtures.SafeUpdateTests.write
    read = fixtures.SafeUpdateTests.read
    active = fixtures.SafeUpdateTests.active

    def setUp(self):
        fixtures.SafeUpdateTests.setUp(self)
        target = self.data / 'cage/appimage' / 'org.example.UpdateProof'
        target.parent.mkdir(parents=True)
        self.state.rename(target); self.state = target; self.previous = target / 'prefix'
        self.appdir = self.root / 'AppDir'; self.metadata = self.appdir / 'usr/share/cage/org.example.UpdateProof/desktop.json'
        self.metadata.parent.mkdir(parents=True)
        shutil.copytree(self.old.parent / 'seed', self.metadata.parent / 'seed', symlinks=True)
        shutil.copy2(self.old.parent / 'seed-inventory.json', self.metadata.parent / 'seed-inventory.json')
        wine = self.appdir / 'usr/wine'; shutil.copytree(self.runtime, wine)
        (self.appdir / 'org.example.UpdateProof.svg').write_text('<svg/>')
        old = json.loads(self.old.read_text())
        old['target']['wineDllDirectory'] = '.'
        old.update(format='appimage'); old['state'] = {'namespace': 'cage/appimage'}
        old['desktop'].update(name='Proof', summary='Proof', categories=['Utility'])
        self.initial = plan_identity(old)
        for path in (self.state / 'state.json', self.previous / '.cage-state.json'):
            path.write_text(json.dumps(self.initial))
        self.legacy = self.root / 'legacy.AppImage'; self.legacy.write_bytes(b'\x7fELFlegacy')
        self.modern = self.root / 'baseline.AppImage'; self.modern.write_bytes(b'\x7fELFmanaged')
        Path(str(self.legacy) + '.json').write_text(json.dumps({'schemaVersion': 'cage.appimage-export-result/v0',
            'sha256': hashlib.sha256(self.legacy.read_bytes()).hexdigest(), 'plan': old}))
        self.plan = json.loads(json.dumps(old)); self.plan['state']['managerVersion'] = 1
        self.metadata.write_text(json.dumps(self.plan))
        with patch.dict(os.environ, {'APPIMAGE': str(self.legacy)}):
            installed = integration.integrate(self.appdir, old)
        self.installation = Path(installed['installed']).parent
        receipt = self.installation / 'installation.json'
        data = json.loads(receipt.read_text()); data['schemaVersion'] = 'cage.appimage-installation/v0'
        receipt.write_text(json.dumps(data)); self.original_receipt = receipt.read_bytes()

    def migrate(self):
        self.metadata.write_text(json.dumps(self.plan))
        with patch.dict(os.environ, {'APPIMAGE': str(self.modern)}):
            return integration.migrate(self.appdir, self.metadata, self.plan, self.legacy, [])

    def test_integration_adoption_retains_exact_old_package_and_original_state(self):
        self.assertEqual(self.migrate(), 0)
        self.assertEqual((self.installation / 'application.AppImage').read_bytes(), self.modern.read_bytes())
        receipt = json.loads((self.installation / 'installation.json').read_text())
        self.assertEqual(receipt['schemaVersion'], 'cage.appimage-installation/v1')
        journal = json.loads((self.state / 'appimage-migration.json').read_text())
        backup = self.state / journal['snapshot']
        self.assertEqual((backup / 'previous.AppImage').read_bytes(), self.legacy.read_bytes())
        self.assertEqual((backup / 'integration/installation.json').read_bytes(), self.original_receipt)
        self.assertEqual(self.read(self.active(), 'Documents/story.txt'), 'document v1')

    def test_failed_trial_restores_legacy_integration_and_retains_work(self):
        self.plan['environment']['PROOF_EXIT'] = '7'
        self.assertEqual(self.migrate(), 7)
        self.assertEqual((self.installation / 'installation.json').read_bytes(), self.original_receipt)
        self.assertEqual((self.installation / 'application.AppImage').read_bytes(), self.legacy.read_bytes())
        self.assertEqual(self.active(), self.previous)
        self.assertEqual(len(list((self.state / 'generations').iterdir())), 1)

    def test_error_after_commit_recovers_managed_integration(self):
        real = integration.launch
        def interrupted(*args):
            real(*args)
            raise OSError('interrupted after commit')
        with patch.object(integration, 'launch', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'after commit'):
                self.migrate()
        self.assertNotEqual(self.active(), self.previous)
        self.assertEqual((self.installation / 'application.AppImage').read_bytes(), self.modern.read_bytes())

    def test_retry_after_failed_trial_keeps_both_independent_snapshots(self):
        self.plan['environment']['PROOF_EXIT'] = '7'
        self.assertEqual(self.migrate(), 7)
        self.plan['environment'].pop('PROOF_EXIT')
        self.assertEqual(self.migrate(), 0)
        self.assertEqual(len(list((self.state / 'legacy-snapshots').iterdir())), 2)

    def test_partial_integration_is_retained_and_old_integration_restored(self):
        real = integration.integrate
        def interrupt(root, plan, **options):
            if options.get('remove'):return real(root, plan, **options)
            directory = integration.installed_directory(plan)
            directory.mkdir(parents=True)
            (directory / 'partial-work').write_text('retain me')
            raise OSError('interrupted installation')
        with patch.object(integration, 'integrate', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted installation'):self.migrate()
        self.assertEqual((self.installation / 'installation.json').read_bytes(), self.original_receipt)
        self.assertEqual(len(list((self.state / 'legacy-snapshots').glob('*/integration-recovery-*/installation/partial-work'))), 1)
        self.assertEqual(self.active(), self.previous)

    def test_corrupt_recovery_backup_does_not_move_current_installation(self):
        self.plan['environment']['PROOF_EXIT'] = '7'
        self.assertEqual(self.migrate(), 7)
        journal = json.loads((self.state / 'appimage-migration.json').read_text())
        backup = self.state / journal['snapshot']
        (backup / 'desktop').write_text('changed backup')
        with self.assertRaisesRegex(integration.DesktopError, 'without moving files'):
            integration.recover_migration(self.appdir, self.plan)
        self.assertEqual((self.installation / 'installation.json').read_bytes(), self.original_receipt)

    def test_linked_unknown_installation_file_is_never_followed(self):
        external = self.root / 'private.txt'; external.write_text('private')
        (self.installation / 'unexpected').symlink_to(external)
        with self.assertRaisesRegex(integration.DesktopError, 'linked or untracked'):self.migrate()
        self.assertFalse(list((self.state / 'legacy-snapshots').glob('*/integration')))
        self.assertEqual(external.read_text(), 'private')

    def test_unintegrated_legacy_package_can_explicitly_adopt_a_menu_entry(self):
        integration.integrate(self.appdir, self.plan, remove=True)
        self.assertEqual(self.migrate(), 0)
        self.assertEqual((self.installation / 'application.AppImage').read_bytes(), self.modern.read_bytes())
        journal = json.loads((self.state / 'appimage-migration.json').read_text())
        self.assertFalse(journal['hadIntegration'])

    def test_package_change_during_retention_refuses_before_integration_changes(self):
        real = integration.copy_file
        def changed(source, destination):
            result = real(source, destination)
            if Path(destination).name == 'baseline.AppImage':self.modern.write_bytes(b'changed package')
            return result
        with patch.object(integration, 'copy_file', side_effect=changed):
            with self.assertRaisesRegex(integration.DesktopError, 'changed while copying'):self.migrate()
        self.assertEqual((self.installation / 'installation.json').read_bytes(), self.original_receipt)
        self.assertEqual(self.active(), self.previous)

    def test_old_migration_recovery_cannot_reset_integration_after_a_later_rollback(self):
        self.assertEqual(self.migrate(), 0)
        record = _read_generations(self.state)
        previous = record['active']; later = 'generations/' + 'f' * 32
        shutil.copytree(self.state / previous, self.state / later, symlinks=True)
        record['generations'].append({**record['generations'][-1], 'prefix': later, 'action': 'rollback'})
        record.update(active=later, previous=previous)
        (self.state / 'state.json').write_text(json.dumps(record))
        before = (self.installation / 'installation.json').read_bytes()
        with self.assertRaisesRegex(integration.DesktopError, 'later generation'):
            integration.recover_migration(self.appdir, self.plan)
        self.assertEqual((self.installation / 'installation.json').read_bytes(), before)


class SourcePreparationTests(unittest.TestCase):
    def test_repeated_preparation_verifies_bytes_and_refuses_changed_staging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'sources').mkdir()
            archive = root / 'sources/app.zip'
            with zipfile.ZipFile(archive, 'w') as z:z.writestr('app.exe', b'pinned application')
            manifest = Manifest.from_dict({'schemaVersion': 'cage.app/v0', 'name': 'portable-proof', 'version': '1',
                'runtime': {'provider': 'wine', 'version': '11.0'},
                'sources': [{'id': 'app', 'type': 'archive', 'policy': 'redistributable',
                             'path': 'sources/app.zip', 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}]})
            result = prepare_portable_source(manifest, workspace=root)
            self.assertEqual(prepare_portable_source(manifest, workspace=root), result)
            staged = Path(result['stagedPath']) / 'app.exe'; staged.write_bytes(b'changed app')
            with self.assertRaisesRegex(MediaStageError, 'differs from the pinned archive'):
                prepare_portable_source(manifest, workspace=root)
            self.assertEqual(staged.read_bytes(), b'changed app')
            staged.unlink(); staged.symlink_to(archive)
            with self.assertRaisesRegex(MediaStageError, 'linked'):
                prepare_portable_source(manifest, workspace=root)


if __name__ == '__main__':
    unittest.main()
