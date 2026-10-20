"""Deployment recovery follows the committed prefix, including ambiguous exits."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact import updates
from runtime.desktop_launch import DesktopError


class FlatpakUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = [self.package(v) for v in ('1', '2')]
        self.current_plan = self.old[0]['plan']
        self.current_identity = self.old[0]['identity']
        self.installed = []
        self.fail_trial = False
        self.fail_after_commit = False
        self.commands = []
        def command(arguments, environment, capture=True):
            self.commands.append(arguments)
            if '--command=cat' in arguments:
                return json.dumps(self.current_plan)
            if '--cage-state-info' in arguments:
                return json.dumps({'state': {'active': 'prefix', 'generations': [
                    {'prefix': 'prefix', 'identity': self.current_identity}]}})
            if arguments[0] == 'install':
                digest = Path(arguments[-1]).stem
                entry = self.old[0] if digest == self.old[0]['sha256'] else self.new[0]
                self.current_plan = entry['plan']
                self.installed.append(digest)
            if '--cage-update' in arguments:
                if self.fail_trial:
                    raise DesktopError('trial failed')
                self.current_identity = self.new[0]['identity']
                if self.fail_after_commit:
                    raise DesktopError('interrupted after state committed')
            return ''
        self.mock = patch('artifact.updates._command', side_effect=command)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def package(self, version):
        package = self.root / (version + '.flatpak')
        package.write_bytes(('package ' + version).encode())
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        plan = {'format': 'flatpak', 'branch': 'stable', 'seedDigest': version,
                'target': {'architecture': 'aarch64'},
                'desktop': {'id': 'org.example.App', 'updates': {'profile': 'p/v1'}},
                'state': {'managerVersion': 1}}
        Path(str(package) + '.json').write_text(json.dumps({
            'schemaVersion': 'cage.flatpak-export-result/v0', 'sha256': digest, 'plan': plan}))
        return {'sha256': digest, 'identity': updates.identity(plan), 'plan': plan}, package

    def run_update(self):
        return updates.update_flatpak(self.new[1], self.old[1], cache=self.root / 'cache')

    def test_success_retains_both_artifacts_before_first_deployment(self):
        result = self.run_update()
        self.assertTrue(result['updated'])
        for entry, source in (self.old, self.new):
            self.assertEqual((self.root / 'cache' / (entry['sha256'] + '.flatpak')).read_bytes(), source.read_bytes())
        journal = json.loads((self.root / 'cache/transaction.json').read_text())
        self.assertEqual(journal['status'], 'committed')
        self.assertEqual(self.installed, [self.new[0]['sha256']])

    def test_failed_trial_restores_previous_deployment(self):
        self.fail_trial = True
        with self.assertRaisesRegex(DesktopError, 'trial failed'):
            self.run_update()
        self.assertEqual(self.installed, [self.new[0]['sha256'], self.old[0]['sha256']])
        self.assertEqual(self.current_identity, self.old[0]['identity'])

    def test_error_after_durable_commit_keeps_package_matching_new_state(self):
        self.fail_after_commit = True
        with self.assertRaisesRegex(DesktopError, 'interrupted after'):
            self.run_update()
        self.assertEqual(self.installed, [self.new[0]['sha256'], self.new[0]['sha256']])

    def test_power_interruption_recovery_reads_committed_state(self):
        self.run_update()
        self.current_identity = self.old[0]['identity']
        result = updates.recover_flatpak(self.root / 'cache')
        self.assertEqual(result['packageSha256'], self.old[0]['sha256'])
        retained = self.root / 'cache' / (self.old[0]['sha256'] + '.flatpak')
        retained.write_bytes(b'corrupt')
        with self.assertRaisesRegex(DesktopError, 'changed'):
            updates.recover_flatpak(self.root / 'cache')

    def test_wrong_identity_receipt_or_installed_version_changes_nothing(self):
        self.current_plan = self.new[0]['plan']
        with self.assertRaisesRegex(DesktopError, 'does not match'):
            self.run_update()
        self.assertEqual(self.installed, [])
        self.new[1].write_bytes(b'corrupted bundle')
        with self.assertRaisesRegex(DesktopError, 'mismatch'):
            self.run_update()
        self.assertEqual(self.installed, [])


if __name__ == '__main__':
    unittest.main()
