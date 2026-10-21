"""Legacy deployment recovery never invokes controls in a pre-manager package."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from artifact import updates
from runtime.desktop_launch import DesktopError, _read_generations, _generation
from tests import test_flatpak_updates as fixtures


class LegacyFlatpakTests(unittest.TestCase):
    package = fixtures.FlatpakUpdateTests.package

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = [self.package(v) for v in ('1', '2')]
        for entry, path in (self.old, self.new):
            entry['plan']['application'] = {'name': 'proof', 'version': '1'}
        self.old[0]['plan']['state'] = {'schemaVersion': 'cage.desktop-state/v0'}
        self.old[0]['plan']['desktop'].pop('updates')
        for entry, path in (self.old, self.new):
            entry['identity'] = updates.identity(entry['plan'])
            Path(str(path) + '.json').write_text(json.dumps({'schemaVersion': 'cage.flatpak-export-result/v0',
                                                           'sha256': entry['sha256'], 'plan': entry['plan']}))
        self.state = self.root / 'state'; prefix = self.state / 'prefix'
        (prefix / 'drive_c').mkdir(parents=True)
        (prefix / 'drive_c/App.exe').write_text('old executable')
        (prefix / '.cage-state.json').write_text(json.dumps(self.old[0]['identity']))
        (self.state / 'state.json').write_text(json.dumps(self.old[0]['identity']))
        self.current = self.old[0]; self.installs = []; self.fail = False; self.after_commit = False; self.wrong_directory = False
        self.commands = []
        def command(arguments, environment, capture=True):
            self.commands.append(arguments)
            if '--command=cat' in arguments:return json.dumps(self.current['plan'])
            if arguments[0] == 'ps':return ''
            if arguments[0] == 'install':
                digest = Path(arguments[-1]).stem
                self.current = self.new[0] if digest == self.new[0]['sha256'] else self.old[0]
                self.installs.append(digest)
            if '--cage-state-info' in arguments:
                self.assertNotEqual(self.current, self.old[0], 'old helpers cannot report generations')
                return json.dumps({'state': _read_generations(self.state),
                                   'stateDirectory': str(self.root / 'other') if self.wrong_directory else str(self.state)})
            if '--cage-migrate' in arguments:
                if self.fail:raise DesktopError('trial failed')
                target = self.state / 'generations' / ('a' * 32)
                target.parent.mkdir(); shutil.copytree(prefix, target)
                (target / '.cage-state.json').write_text(json.dumps(self.new[0]['identity']))
                record = _read_generations(self.state)
                record.update(previous='prefix', active='generations/' + 'a' * 32)
                record['generations'].append({'prefix': record['active'], 'identity': self.new[0]['identity']})
                (self.state / 'state.json').write_text(json.dumps(record))
                if self.after_commit:raise DesktopError('interrupted after commit')
            return ''
        self.mock = patch('artifact.updates._command', side_effect=command); self.mock.start(); self.addCleanup(self.mock.stop)

    def migrate(self):
        return updates.migrate_flatpak(self.new[1], self.old[1], cache=self.root / 'cache', state_dir=self.state)

    def test_adoption_retains_verified_old_state_and_both_packages(self):
        result = self.migrate(); self.assertTrue(result['migrated'])
        snapshot = Path(result['legacySnapshot'])
        self.assertEqual(json.loads((snapshot / 'state.json').read_text()), self.old[0]['identity'])
        self.assertEqual((self.state / 'prefix/drive_c/App.exe').read_text(), 'old executable')
        for entry, _ in (self.old, self.new):self.assertTrue((self.root / 'cache' / (entry['sha256'] + '.flatpak')).is_file())

    def test_trial_failure_restores_exact_old_deployment_without_old_helper_controls(self):
        self.fail = True
        with self.assertRaisesRegex(DesktopError, 'trial failed'):self.migrate()
        self.assertEqual(self.installs, [self.new[0]['sha256'], self.old[0]['sha256']])
        self.assertEqual(json.loads((self.state / 'state.json').read_text()), self.old[0]['identity'])

    def test_error_after_commit_and_power_recovery_follow_new_state(self):
        self.after_commit = True
        with self.assertRaisesRegex(DesktopError, 'after commit'):self.migrate()
        self.assertEqual(self.installs, [self.new[0]['sha256'], self.new[0]['sha256']])
        recovered = updates.recover_flatpak(self.root / 'cache')
        self.assertEqual(recovered['packageSha256'], self.new[0]['sha256'])

    def test_wrong_state_namespace_refuses_trial_and_recovers_old_deployment(self):
        self.wrong_directory = True
        with self.assertRaisesRegex(DesktopError, 'different state directory'):self.migrate()
        self.assertFalse(any('--cage-migrate' in cmd for cmd in self.commands))
        self.assertEqual(self.current, self.old[0])

    def test_unknown_state_and_changed_legacy_package_do_not_deploy(self):
        (self.state / 'state.json').write_text('{}')
        with self.assertRaises(DesktopError):self.migrate()
        self.assertEqual(self.installs, [])
        self.old[1].write_bytes(b'tampered')
        with self.assertRaisesRegex(DesktopError, 'mismatch'):self.migrate()
        self.assertEqual(self.installs, [])


if __name__ == '__main__':unittest.main()
