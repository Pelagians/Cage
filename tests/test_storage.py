"""Storage controls must fail closed around user work and recovery artifacts."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from artifact import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {'HOME': str(self.root / 'home'),
                                                   'XDG_DATA_HOME': str(self.root / 'data')})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def context(self):
        context = self.root / 'export.AppImage.build'
        (context / 'AppDir/usr/share').mkdir(parents=True)
        (context / 'AppDir/usr/share/program').write_bytes(b'old-build-content')
        (context / 'export-plan.json').write_text('{"proof": true}')
        (context / 'appdir-inventory.json').write_text('[]')
        bundle = self.root / 'source-bundle'
        bundle.mkdir()
        (bundle / 'settings').write_text('keep source')
        package = self.root / 'export.AppImage'
        package.write_bytes(b'complete installable package')
        artifact = {'kind': 'file', 'path': str(package), 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}
        with storage.build_lock(context):
            storage.complete_export(context, bundle, 'appimage', artifact)
        return context, package, bundle

    def state(self):
        root = self.root / 'user-state'
        generations = []
        for name in ('prefix', 'generations/' + 'a' * 32, 'generations/' + 'b' * 32):
            path = root / name
            (path / 'drive_c/users/abc/Documents').mkdir(parents=True)
            (path / 'drive_c/users/abc/Documents/work.txt').write_text('user document ' + name)
            identity = {'seedDigest': name}
            (path / '.cage-state.json').write_text(json.dumps(identity))
            generations.append({'prefix': name, 'identity': identity})
        record = {'schemaVersion': 'cage.desktop-generations/v1', 'active': generations[-1]['prefix'],
                  'previous': generations[-2]['prefix'], 'generations': generations}
        (root / 'state.json').write_text(json.dumps(record))
        (root / 'launch.lock').touch()
        (root / 'generations' / ('c' * 32)).mkdir()
        (root / 'generations' / ('c' * 32) / 'saved-work.txt').write_text('failed trial work')
        return root

    def contents(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_legacy_snapshots_and_interrupted_migration_remain_protected(self):
        root = self.state()
        backup = root / 'legacy-snapshots/original'
        backup.mkdir(parents=True)
        (backup / 'snapshot.json').write_text('{"schemaVersion":"cage.legacy-snapshot/v1"}')
        (backup / 'saved-work.txt').write_text('original work')
        (root / 'appimage-migration.json').write_text('{"status":"prepared"}')
        before = self.contents(root)
        info = storage.inspect_state(root)
        self.assertTrue(info['legacySnapshots'][0]['protected'])
        self.assertTrue(info['legacySnapshots'][0]['complete'])
        self.assertIn('--cage-recover-migration', info['recovery'])
        self.assertFalse(storage.prune_context(root, min_age_hours=0, apply=True)['eligible'])
        self.assertEqual(self.contents(root), before)

    def test_preview_then_prune_preserves_package_bundle_and_provenance(self):
        context, package, bundle = self.context()
        before = self.contents(self.root)
        preview = storage.prune_context(context, min_age_hours=0)
        self.assertTrue(preview['eligible'], preview)
        self.assertEqual(self.contents(self.root), before)
        self.assertIsNone(preview['usage']['reclaimableBytes'])
        result = storage.prune_context(context, min_age_hours=0, apply=True)
        self.assertEqual(result['removed'], ['AppDir'])
        self.assertFalse((context / 'AppDir').exists())
        self.assertEqual(package.read_bytes(), before[package.name])
        self.assertEqual((bundle / 'settings').read_text(), 'keep source')
        self.assertTrue((context / 'export-plan.json').is_file())
        self.assertTrue((context / 'appdir-inventory.json').is_file())
        self.assertEqual(storage.read_json(context / storage.MARKER)['status'], 'cleaned')
        self.assertEqual(storage.prune_context(context, min_age_hours=0, apply=True)['removed'], [])

    def test_untracked_failed_or_changed_staging_is_never_deleted(self):
        context, package, _ = self.context()
        (context / 'AppDir/user-document.txt').write_text('saved work')
        result = storage.prune_context(context, min_age_hours=0, apply=True)
        self.assertFalse(result['eligible'])
        self.assertTrue((context / 'AppDir/user-document.txt').exists())
        self.assertTrue(package.exists())
        unknown = self.root / 'unknown.build'
        unknown.mkdir()
        self.assertFalse(storage.prune_context(unknown, min_age_hours=0, apply=True)['eligible'])
        (context / 'state.json').write_text('{}')
        with self.assertRaises(storage.StorageError):
            storage.complete_export(context, self.root / 'source-bundle', 'appimage', {'kind': 'file', 'path': str(package), 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()})

    def test_changed_bytes_detected_even_when_size_and_mtime_restored(self):
        context, _, _ = self.context()
        file = context / 'AppDir/usr/share/program'
        old = file.stat()
        file.write_bytes(b'new-build-content')
        os.utime(file, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.assertFalse(storage.prune_context(context, min_age_hours=0, apply=True)['eligible'])
        self.assertTrue(file.exists())

    def test_missing_or_changed_retained_package_blocks_cleanup(self):
        context, package, _ = self.context()
        package.write_bytes(b'altered package')
        self.assertFalse(storage.prune_context(context, min_age_hours=0, apply=True)['eligible'])
        package.unlink()
        self.assertFalse(storage.prune_context(context, min_age_hours=0, apply=True)['eligible'])
        self.assertTrue((context / 'AppDir').exists())

    def test_links_never_lead_cleanup_outside_context(self):
        context, _, bundle = self.context()
        (context / 'AppDir/link').symlink_to(bundle, target_is_directory=True)
        # A producer's symlink is recorded but never followed.
        marker = storage.read_json(context / storage.MARKER)
        marker['entries'] = storage.snapshot(context)
        storage._write_marker(context, marker)
        storage.prune_context(context, min_age_hours=0, apply=True)
        self.assertEqual((bundle / 'settings').read_text(), 'keep source')
        linked = self.root / 'linked'
        linked.symlink_to(context, target_is_directory=True)
        with self.assertRaises(storage.StorageError):
            storage.prune_context(linked, min_age_hours=0, apply=True)
        with self.assertRaises(storage.StorageError):
            storage.prune_context(linked / 'child', min_age_hours=0, apply=True)

    def test_protected_state_and_current_interpreter_overlap_blocks_cleanup(self):
        context, _, _ = self.context()
        self.assertFalse(storage.prune_context(context, min_age_hours=0, protected=[context / 'AppDir'], apply=True)['eligible'])
        with patch('artifact.storage.sys.base_prefix', str(context / 'AppDir/usr/python')):
            self.assertFalse(storage.prune_context(context, min_age_hours=0, apply=True)['eligible'])

    def test_busy_producer_refuses_cleanup_in_another_process(self):
        context, _, _ = self.context()
        process = subprocess.Popen([sys.executable, '-c',
            'import sys;from artifact.storage import build_lock;'
            '\nwith build_lock(sys.argv[1]):\n print("locked",flush=True);sys.stdin.read()\n', str(context)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            result = storage.prune_context(context, min_age_hours=0, apply=True)
            self.assertFalse(result['eligible'])
            self.assertIn('busy', result['reason'])
        finally:
            process.communicate('', timeout=10)

    def test_changes_after_preview_are_rechecked_under_lock(self):
        context, _, _ = self.context()
        real = storage.inspect_context
        def change(*args, **kwargs):
            result = real(*args, **kwargs)
            (context / 'AppDir/new-work').write_text('keep this')
            return result
        with patch('artifact.storage.inspect_context', side_effect=change):
            with self.assertRaises(storage.StorageError):
                storage.prune_context(context, min_age_hours=0, apply=True)
        self.assertTrue((context / 'AppDir/new-work').exists())
        self.assertTrue((context / 'AppDir/usr/share/program').exists())

    def test_late_unknown_file_is_retained_even_after_deletion_started(self):
        context, package, _ = self.context()
        unlink = os.unlink
        def add_work(name, **kwargs):
            if name == 'program':
                (context / 'AppDir/usr/share/new-document').write_text('keep me')
            return unlink(name, **kwargs)
        with patch('artifact.storage.os.unlink', side_effect=add_work):
            with self.assertRaises(OSError):
                storage.prune_context(context, min_age_hours=0, apply=True)
        self.assertEqual((context / 'AppDir/usr/share/new-document').read_text(), 'keep me')
        self.assertTrue(package.exists())

    def test_tool_cache_only_removes_verified_known_downloads_and_preview_is_read_only(self):
        cache = self.root / 'tools'
        cache.mkdir()
        content = b'pinned build tool download'
        digest = hashlib.sha256(content).hexdigest()
        (cache / digest).write_bytes(content)
        (cache / 'unknown').write_text('retain')
        (cache / 'runner').mkdir()
        with patch('artifact.storage.tool_hashes', return_value={digest}):
            storage.prune_tools(cache, min_age_hours=0)
            self.assertFalse(storage.lock_path(cache).exists())
            self.assertTrue((cache / digest).exists())
            result = storage.prune_tools(cache, min_age_hours=0, apply=True)
            self.assertEqual(result['removed'], [digest])
        self.assertEqual((cache / 'unknown').read_text(), 'retain')
        self.assertTrue((cache / 'runner').is_dir())

    def test_state_diagnostics_preserve_all_generations_candidates_and_documents(self):
        state = self.state()
        before = self.contents(state)
        result = storage.doctor(output_dir=self.root / 'dist', state_dirs=[state], required_free_mib=0)
        self.assertFalse(result['healthy'])  # A saved failed candidate needs attention.
        item = result['storage']['states'][0]
        self.assertEqual(len(item['state']['generations']), 3)
        self.assertTrue(item['protected'])
        self.assertEqual(item['retainedCandidates'], ['generations/' + 'c' * 32])
        self.assertEqual(self.contents(state), before)
        self.assertFalse((self.root / 'dist').exists())

    def test_corrupt_index_blocks_pruning_and_corrupt_state_is_reported(self):
        context, _, _ = self.context()
        index = self.root / 'index.json'
        index.write_text('[]')
        with self.assertRaises(storage.StorageError):
            storage.prune_storage(output_dir=self.root, index_path=index, build_dirs=[context], min_age_hours=0, apply=True)
        state = self.state()
        (state / 'state.json').write_text('[]')
        item = storage.inspect_state(state)
        self.assertIn('error', item)
        self.assertTrue(item['protected'])

    def test_missing_or_changed_rollback_package_is_diagnosed_without_removal(self):
        install = self.root / 'installation'
        install.mkdir()
        package = install / 'application.AppImage'
        package.write_bytes(b'old version')
        (install / 'installation.json').write_text(json.dumps({'schemaVersion': 'cage.appimage-installation/v1',
            'package': hashlib.sha256(package.read_bytes()).hexdigest(), 'versions': [{'package': 'versions/new.AppImage', 'sha256': 'b' * 64}]}))
        before = self.contents(install)
        result = storage.doctor(output_dir=self.root / 'dist', package_dirs=[install], required_free_mib=0)
        self.assertFalse(result['healthy'])
        self.assertIn('rollback package', ' '.join(result['problems']))
        self.assertEqual(self.contents(install), before)

    def test_flatpak_and_oci_cleanup_retain_runtime_artifacts(self):
        bundle = self.root / 'bundle-source'
        bundle.mkdir()
        for kind in ('flatpak', 'oci'):
            with self.subTest(kind=kind):
                context = self.root / (kind + '.build')
                context.mkdir()
                (context / 'export-plan.json').write_text('{}')
                for name in storage.DISPOSABLE[kind] - {'linux-state.tar'}:
                    (context / name).mkdir()
                    (context / name / 'content').write_text('disposable')
                image = 'a' * 64
                package = self.root / 'retained.flatpak'
                package.write_bytes(b'package')
                artifact = {'kind': 'file', 'path': str(package), 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}
                if kind == 'oci':
                    artifact = {'kind': 'oci', 'engine': 'podman', 'id': image}
                response = subprocess.CompletedProcess([], 0, image + '\n', '')
                with patch('artifact.storage.subprocess.run', return_value=response) as engine:
                    with storage.build_lock(context):
                        storage.complete_export(context, bundle, kind, artifact)
                    if kind == 'oci':
                        response.returncode = 1
                        self.assertFalse(storage.prune_context(context, min_age_hours=0, apply=True)['eligible'])
                        response.returncode = 0
                    result = storage.prune_context(context, min_age_hours=0, apply=True)
                    self.assertTrue(result['removed'])
                    for call in engine.call_args_list:
                        self.assertEqual(call.args[0][:3], ['podman', 'image', 'inspect'])
                        self.assertEqual(call.args[0][-1], image)
                self.assertTrue(package.exists())
                self.assertTrue((context / 'export-plan.json').exists())

    def test_special_files_and_state_namespaces_cannot_be_registered_as_disposable(self):
        context, package, bundle = self.context()
        artifact = {'kind': 'file', 'path': str(package), 'sha256': hashlib.sha256(package.read_bytes()).hexdigest()}
        os.mkfifo(context / 'AppDir/pipe')
        result = storage.record_export(context, bundle, 'appimage', artifact)
        self.assertFalse(result['managed'])
        self.assertTrue((context / 'AppDir/pipe').exists())
        protected = Path(os.environ['XDG_DATA_HOME']) / 'cage/appimage/fake-build'
        protected.mkdir(parents=True)
        with self.assertRaises(storage.StorageError):
            storage.complete_export(protected, bundle, 'appimage', artifact)

    def test_parent_swap_after_validation_cannot_delete_external_files(self):
        context, _, _ = self.context()
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'program').write_text('external user work')
        snapshot = storage.snapshot
        calls = 0
        def swap(path):
            nonlocal calls
            result = snapshot(path)
            calls += 1
            if calls == 2:
                parent = context / 'AppDir/usr/share'
                parent.rename(parent.with_name('old-share'))
                parent.symlink_to(outside, target_is_directory=True)
            return result
        with patch('artifact.storage.snapshot', side_effect=swap):
            with self.assertRaises(OSError):
                storage.prune_context(context, min_age_hours=0, apply=True)
        self.assertEqual((outside / 'program').read_text(), 'external user work')

    def test_special_metadata_and_lock_files_fail_without_blocking(self):
        path = self.root / 'index.json'
        os.mkfifo(path)
        result = storage.storage_status(output_dir=self.root / 'dist', index_path=path)
        self.assertTrue(result['issues'])
        state = self.state()
        (state / 'launch.lock').unlink()
        os.mkfifo(state / 'launch.lock')
        self.assertIn('error', storage.inspect_state(state))
        context, _, _ = self.context()
        storage.lock_path(context).unlink()
        os.mkfifo(storage.lock_path(context))
        self.assertFalse(storage.prune_context(context, min_age_hours=0, apply=True)['eligible'])

    def test_retained_package_flush_failure_prevents_any_deletion(self):
        context, _, _ = self.context()
        with patch('artifact.storage.os.fsync', side_effect=OSError('disk I/O error')):
            with self.assertRaises(OSError):
                storage.prune_context(context, min_age_hours=0, apply=True)
        self.assertTrue((context / 'AppDir/usr/share/program').exists())
        self.assertEqual(storage.read_json(context / storage.MARKER)['status'], 'complete')

    def test_diagnostics_report_missing_bundle_and_malformed_target(self):
        result = storage.doctor(output_dir=self.root / 'dist', bundle='missing-application', required_free_mib=0)
        self.assertFalse(result['healthy'])
        bundle = self.root / 'broken-bundle'
        (bundle / 'metadata').mkdir(parents=True)
        (bundle / 'metadata/native-launch.json').write_text('[]')
        with patch('artifact.inspection.verify_bundle', return_value={'valid': False, 'errors': ['invalid metadata']}):
            result = storage.doctor(output_dir=self.root / 'dist', bundle=bundle, required_free_mib=0)
        self.assertFalse(result['healthy'])
        self.assertIn('JSON object required', ' '.join(result['problems']))

    def test_cli_preview_apply_and_doctor_exit_codes(self):
        context, package, _ = self.context()
        base = [sys.executable, '-m', 'cage']
        flags = ['--output-dir', str(self.root), '--min-age-hours', '0']
        process = subprocess.run([*base, 'storage', 'prune', *flags], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(json.loads(process.stdout)['applied'])
        self.assertTrue((context / 'AppDir').exists())
        process = subprocess.run([*base, 'storage', 'prune', *flags, '--apply'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse((context / 'AppDir').exists())
        self.assertTrue(package.exists())
        process = subprocess.run([*base, 'doctor', '--output-dir', str(self.root), '--required-free-mib', '1e99'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 15, process.stderr)
        self.assertFalse(json.loads(process.stdout)['healthy'])


if __name__ == '__main__':
    unittest.main()
