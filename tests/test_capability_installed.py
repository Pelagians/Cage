"""Signing evidence stays scoped; installed/runtime claims require native CI."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from artifact import releases
from tests.test_capability_delivery import plan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installed_probe', ROOT/'scripts/test-capability-installed.py')
installed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installed)


class InstalledProbeEvidenceTests(unittest.TestCase):
    def write(self, path, value):
        Path(path).write_text(json.dumps(value))

    def test_device_and_hotplug_are_blocked_even_when_synthetic_probe_passes(self):
        p = plan()
        # The installed suite deliberately signs a hardware-free probe recipe.
        p['recipe']['permissions']['requests'] = [r for r in p['recipe']['permissions']['requests'] if r['kind'] != 'device-class']
        release = {'entry': {'format': 'appimage', 'plan': p, 'package': {'sha256': 'a'*64}}}
        sessions = [{'status': 'passed', 'settingsPreserved': True, 'stateCounter': i, 'operation': 'policy-rollback'} for i in (4,5,6)]
        with tempfile.TemporaryDirectory() as tmp:
            result = installed.proof(self, release, {}, sessions, Path(tmp)/'proof.json')
        cases = result['capabilityQualification']['cases']
        self.assertEqual(cases['devices']['status'], 'blocked')
        self.assertEqual(cases['hotplug']['status'], 'blocked')
        self.assertEqual(result['physicalUsbSynchronization'], 'unqualified')
        self.assertEqual(result['myHarmonyWorkflow'], 'not-qualified-by-probe-suite')
        self.assertEqual(set(k for k,v in cases.items() if v['status'] == 'passed'), {'baseline','filesystem','network'})

    def test_missing_or_failed_candidate_rollback_cannot_create_proof(self):
        release = {'entry': {'format': 'appimage', 'plan': plan(), 'package': {'sha256': 'a'*64}}}
        for sessions in ([], [{'status':'passed'}]*3, [{'status':'failed', 'settingsPreserved':True, 'stateCounter':i, 'operation':'policy-rollback'} for i in (4,5,6)]):
            with self.subTest(sessions=sessions), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)/'proof.json'
                with self.assertRaisesRegex(RuntimeError, 'actual compatible policy'):
                    installed.proof(self, release, {}, sessions, output)
                self.assertFalse(output.exists())

    def test_fresh_consumer_restores_environment_without_removing_state(self):
        import os
        before = dict(os.environ)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                with installed.fresh_consumer(root) as home:
                    sentinel = home/'recovery'; sentinel.write_bytes(b'retain')
                    self.assertEqual(Path.home(), home)
                    raise RuntimeError('interrupted')
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(sentinel.read_bytes(), b'retain')
