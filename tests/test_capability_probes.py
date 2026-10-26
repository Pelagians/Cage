import importlib.util
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('capability_probe',ROOT/'tests/probes/capability_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class CapabilityProbeTests(unittest.TestCase):
    def test_runtime_directory_requires_ownership_private_mode_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);runtime=root/'runtime';runtime.mkdir(mode=0o700)
            self.assertTrue(probe.private_runtime_directory(runtime))
            runtime.chmod(0o755)
            self.assertFalse(probe.private_runtime_directory(runtime))
            runtime.chmod(0o700)
            with patch.object(probe.os,'getuid',return_value=os.getuid()+1):
                self.assertFalse(probe.private_runtime_directory(runtime))
            link=root/'link';link.symlink_to(runtime)
            self.assertFalse(probe.private_runtime_directory(link))
            self.assertFalse(probe.private_runtime_directory(root/'missing'))
            self.assertFalse(probe.private_runtime_directory(''))

    def test_disposable_filesystem_observations_do_not_claim_qualification(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);read=root/'read';write=root/'write';read.mkdir();write.mkdir()
            canary=read/'canary';canary.write_bytes(b'cage-probe-canary\n')
            args=types.SimpleNamespace(read=canary,write=write,denied=root/'missing',protected=root/'missing2',port=None,abstract=None,device=None,package=None,runtime=None)
            result=probe.observe(args)
            self.assertEqual(result['status'],'observed');self.assertTrue(result['filesystem']['read'])
            self.assertTrue(result['filesystem']['write']);self.assertFalse(result['filesystem']['siblingRead'])
            self.assertEqual(list(write.iterdir()),[]);self.assertEqual(list(read.iterdir()),[canary])
            self.assertIn('not-an-application',result['qualification'])


class CapabilityEvidenceTests(unittest.TestCase):
    def test_missing_observations_and_hardware_are_blocked(self):
        from tests.test_capability_contract import recipe
        from core.capabilities import compile_capabilities
        spec=importlib.util.spec_from_file_location('parity_evidence',ROOT/'scripts/check-capability-parity-evidence.py')
        checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
        cases=checker.evaluate(compile_capabilities(recipe(),'oci'),{},{},{})
        self.assertTrue(all(case['status']=='blocked' for case in cases.values()))
        linux={'baseline':{'noNewPrivileges':True,'zeroCapabilities':True,'seccomp':True},
               'filesystem':{'packageMutation':False,'runtimeMutation':False,'protectedRead':False}}
        control={'controls':{'protectedRead':True}}
        self.assertEqual(checker.evaluate(compile_capabilities(recipe(),'oci'),linux,{},control)['baseline']['status'],'passed')
        linux['baseline']['zeroCapabilities']=False
        self.assertEqual(checker.evaluate(compile_capabilities(recipe(),'oci'),linux,{},control)['baseline']['status'],'failed')
