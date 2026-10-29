"""Successful proof cleanup preserves data and refuses unrelated or changed state."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.proof_storage import ProofPayloads


class ProofStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.evidence = Path(temporary.name) / 'proof'
        self.evidence.mkdir()
        self.state = self.evidence / 'data/app'
        env = patch.dict(os.environ, {'CAGE_TEST_DISCARD_PREFIXES': '1'})
        env.start()
        self.addCleanup(env.stop)

    def populate(self):
        generations = []
        for name in ['prefix', 'generations/' + 'a' * 32]:
            prefix = self.state / name
            system = prefix / 'drive_c/windows/system32'
            system.mkdir(parents=True)
            (system / 'wine.dll').write_bytes(b'MZ-original Wine runtime')
            (system / 'notes.exe').write_text('saved non-executable file')
            docs = prefix / 'drive_c/users/test/Documents'
            docs.mkdir(parents=True)
            (docs / 'saved.dll').write_bytes(b'MZ-user saved data')
            (prefix / 'user.reg').write_text('saved settings')
            identity = {'seedDigest': name}
            (prefix / '.cage-state.json').write_text(json.dumps(identity))
            generations.append({'prefix': name, 'identity': identity})
        (self.state / 'state.json').write_text(json.dumps({
            'schemaVersion': 'cage.desktop-generations/v1', 'active': generations[-1]['prefix'],
            'previous': 'prefix', 'generations': generations}))
        (self.state / 'launch.lock').touch()
        (self.evidence / 'result.json').write_text('{"status":"passed"}')
        (self.evidence / 'rollback.flatpak').write_bytes(b'rollback package')

    def test_success_removes_only_recorded_runtime_and_keeps_evidence_data_and_candidates(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        # A failed candidate and later unknown files are never adopted implicitly.
        candidate = self.state / ('generations/' + 'b' * 32) / 'drive_c/windows/system32'
        candidate.mkdir(parents=True)
        (candidate / 'wine.dll').write_bytes(b'MZ-candidate diagnostic')
        unknown = self.state / 'prefix/drive_c/windows/system32/unknown.dll'
        unknown.write_bytes(b'MZ-new unknown file')
        before = {p: p.read_bytes() for p in self.evidence.rglob('*') if p.is_file()
                  and not (p.name == 'wine.dll' and candidate not in p.parents)}
        result = cleanup.finish()
        self.assertEqual(result['status'], 'cleaned')
        self.assertEqual(len(result['removedFiles']), 2)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data, str(path))
        self.assertTrue((self.evidence / 'runtime-payload-inventory.json').exists())
        self.assertTrue((self.state / 'retired-test-payload.json').exists())

    def test_no_success_callback_retains_failed_proof_payloads(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        self.assertTrue((self.state / 'prefix/drive_c/windows/system32/wine.dll').exists())
        self.assertFalse((self.evidence / 'removed-runtime-files.log').exists())

    def test_tampered_runtime_blocks_all_deletion_even_with_restored_mtime(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        path = self.state / 'generations' / ('a' * 32) / 'drive_c/windows/system32/wine.dll'
        info = path.stat()
        path.write_bytes(path.read_bytes().replace(b'original', b'modified'))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'changed'):
            cleanup.finish()
        self.assertTrue((self.state / 'prefix/drive_c/windows/system32/wine.dll').exists())

    def test_existing_or_nonprivate_state_is_refused(self):
        self.populate()
        with self.assertRaisesRegex(ValueError, 'fresh'):
            ProofPayloads(self.state, self.evidence)
        with self.assertRaisesRegex(ValueError, 'workspace'):
            ProofPayloads(self.evidence.parent / 'unrelated-app', self.evidence)

    def test_busy_proof_cannot_be_cleaned(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        with (self.state / 'launch.lock').open() as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                cleanup.finish()
        self.assertTrue((self.state / 'prefix/drive_c/windows/system32/wine.dll').exists())

    def test_replaced_state_or_linked_ancestor_is_refused(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        moved = self.state.with_name('saved-original')
        self.state.rename(moved)
        self.populate()
        with self.assertRaisesRegex(ValueError, 'replaced'):
            cleanup.finish()
        self.assertTrue((moved / 'prefix/drive_c/windows/system32/wine.dll').exists())

    def test_debug_opt_out_keeps_runtime(self):
        with patch.dict(os.environ, {'CAGE_TEST_DISCARD_PREFIXES': '0'}):
            cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        self.assertEqual(cleanup.finish()['status'], 'retained')
        self.assertTrue((self.state / 'prefix/drive_c/windows/system32/wine.dll').exists())

    def test_links_and_empty_disposable_sets_do_not_fail_a_successful_proof(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        for prefix in [self.state / 'prefix', self.state / 'generations' / ('a' * 32)]:
            path = prefix / 'drive_c/windows/system32/wine.dll'
            path.unlink()
            source = prefix / 'drive_c/users/test/Documents/saved.dll'
            path.symlink_to(source)
            os.link(source, path.with_name('shared.dll'))
        cleanup.record()
        result = cleanup.finish()
        self.assertEqual(result['removedFiles'], [])
        self.assertIn('no independent', result['reason'])
        self.assertTrue((self.state / 'prefix/drive_c/windows/system32/wine.dll').is_symlink())

    def test_symlinked_state_parent_cannot_redirect_cleanup(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        moved = self.evidence / 'saved-data'
        self.state.parent.rename(moved)
        self.state.parent.symlink_to(moved, target_is_directory=True)
        from artifact.storage import StorageError
        with self.assertRaises(StorageError):
            cleanup.finish()
        self.assertTrue((moved / 'app/prefix/drive_c/windows/system32/wine.dll').exists())

    def test_private_flatpak_namespace_is_supported_but_standard_app_data_is_not(self):
        with patch.dict(os.environ, {'HOME': str(self.evidence / 'home')}):
            data = Path.home() / '.var/app/app/data'
            ProofPayloads(data / ('cage-update-proof-' + 'a' * 32) / 'app', self.evidence)
            with self.assertRaises(ValueError):
                ProofPayloads(data / 'app', self.evidence.parent / 'other-proof')


    def test_update_claims_private_state_before_appimage_installation(self):
        import importlib.util
        import sys
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('cleanup_update_proof', root / 'scripts/test-update-poc.py')
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', [str(root / 'scripts'), *sys.path]):
            spec.loader.exec_module(module)
        baseline, candidate = self.evidence / 'baseline.AppImage', self.evidence / 'candidate.AppImage'
        baseline.write_bytes(b'baseline package')
        candidate.write_bytes(b'candidate package')
        evidence = self.evidence / 'fresh-run'
        state = evidence / 'data/cage/appimage' / module.gui.APP
        def install(argv, **kwargs):
            self.assertIn('--cage-install', argv)
            # The real integration installer creates state for its DPI policy.
            state.mkdir(parents=True)
            raise RuntimeError('stop after installation')
        with patch.dict(os.environ, {'CAGE_TEST_EVIDENCE': str(evidence), 'CAGE_TEST_DESKTOP_INTEGRATION': '0'}), \
             patch.object(sys, 'argv', ['test-update-poc.py', 'appimage', str(baseline), str(candidate)]), \
             patch.object(module, 'ProofPayloads', wraps=ProofPayloads) as claim, \
             patch.object(module.subprocess, 'check_output', side_effect=install):
            with self.assertRaisesRegex(RuntimeError, 'stop after installation'):
                module.main()
        claim.assert_called_once_with(state, evidence)
        self.assertTrue(state.exists())


    def test_missing_or_failed_qualification_blocks_all_deletion(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        result = self.evidence / 'result.json'
        for status in (None, 'failed', 'pending'):
            with self.subTest(status=status):
                if status is None:
                    result.unlink()
                else:
                    result.write_text(json.dumps({'status': status}))
                with self.assertRaisesRegex(ValueError, 'saved passing qualification'):
                    cleanup.finish()
                self.assertTrue((self.state / 'prefix/drive_c/windows/system32/wine.dll').exists())
                self.assertFalse((self.evidence / 'runtime-payload-inventory.json').exists())
        result.write_text('{"status":"passed"}')
        (self.evidence / 'functional-test.json').write_text('{"status":"failed"}')
        with self.assertRaisesRegex(ValueError, 'saved passing qualification'):
            cleanup.finish()
        self.assertFalse((self.evidence / 'removed-runtime-files.log').exists())

    def test_existing_cleanup_evidence_is_never_overwritten(self):
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        paths = [self.evidence / name for name in (
            'payload-cleanup.json', 'runtime-payload-inventory.json', 'removed-runtime-files.log')]
        paths.append(self.state / 'retired-test-payload.json')
        for path in paths:
            with self.subTest(path=path.name):
                path.write_bytes(b'previous qualification evidence')
                with self.assertRaisesRegex(ValueError, 'existing cleanup evidence'):
                    cleanup.finish()
                self.assertEqual(path.read_bytes(), b'previous qualification evidence')
                self.assertTrue((self.state / 'prefix/drive_c/windows/system32/wine.dll').exists())
                path.unlink()

    def test_interrupted_cleanup_journal_survives_actual_ci_collection(self):
        import importlib.util
        cleanup = ProofPayloads(self.state, self.evidence)
        self.populate()
        cleanup.record()
        unlink = os.unlink
        removed = []
        def interrupt(name, **kwargs):
            if removed:
                raise OSError('interrupted cleanup')
            unlink(name, **kwargs)
            removed.append(name)
        with patch('scripts.proof_storage.os.unlink', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted cleanup'):
                cleanup.finish()
        journal = self.evidence / 'removed-runtime-files.log'
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertFalse((self.state / records[0]['path']).exists())
        self.assertTrue((self.state / 'generations' / ('a' * 32) / 'drive_c/windows/system32/wine.dll').exists())
        self.assertEqual((self.state / 'prefix/user.reg').read_text(), 'saved settings')
        self.assertEqual((self.evidence / 'rollback.flatpak').read_bytes(), b'rollback package')
        self.assertFalse((self.state / 'retired-test-payload.json').exists())
        spec = importlib.util.spec_from_file_location('cleanup_evidence_collector',
            Path(__file__).resolve().parents[1] / 'scripts/collect-onboarding-evidence.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        destination = self.evidence.parent / 'collected'
        collector.collect(self.evidence, destination)
        self.assertEqual((destination / journal.name).read_bytes(), journal.read_bytes())
        self.assertTrue((destination / 'runtime-payload-inventory.json').is_file())
        self.assertFalse((destination / 'data').exists())


if __name__ == '__main__':
    unittest.main()
