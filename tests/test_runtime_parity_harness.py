"""Producer-fixture safeguards; actual adapter execution is a separate x86 CI job."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.manifest import Manifest
from core.capabilities import compile_capabilities

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_parity_harness',ROOT/'scripts/test-capability-runtimes.py')
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)


class RuntimeParityHarnessTests(unittest.TestCase):
    def test_real_fixture_declares_one_contract_for_all_formats(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'inputs').mkdir();(root/'inputs/probe.zip').write_bytes(b'fixture')
            paths={name:root/(name+' café') for name in ('read','write','replacement','denied','protected')}
            raw=harness.fixture_recipe('io.github.Pelagians.Cage.ParityFixture',root,paths)
            manifest=Manifest.from_dict(raw)
            plans=[compile_capabilities(manifest,kind) for kind in ('oci','flatpak','appimage')]
            self.assertEqual(len({p['contractDigest'] for p in plans}),1)
            for kind in ('oci','flatpak','appimage'):
                denied=compile_capabilities(manifest,kind,decisions={'network':'deny','devices':'deny'})
                self.assertTrue(denied['launchAllowed'])
                self.assertTrue(all(not item['grant'] for item in denied['requests'] if item['id'] in ('network','devices')))

    def test_synthetic_fixture_refuses_preexisting_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=harness.NullFixture('unit-test')
            fixture.path=Path(temporary)/'occupied';fixture.path.write_text('preserve')
            with patch.object(harness.subprocess,'run') as run:
                with self.assertRaisesRegex(RuntimeError,'already occupied'):fixture.create()
                run.assert_not_called()
            self.assertEqual(fixture.path.read_text(),'preserve')

    def test_linux_probe_file_transport_works_with_closed_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);read=root/'read';write=root/'write';read.mkdir();write.mkdir()
            (read/'canary').write_bytes(b'cage-probe-canary\n')
            output=root/'result.json';ready=root/'ready.json'
            args=[sys.executable,str(ROOT/'tests/probes/capability_probe.py'),'--read',str(read/'canary'),'--write',str(write),
                  '--denied',str(root/'denied'),'--protected',str(root/'protected'),'--output',str(output),
                  '--device','/dev/cage-parity-no-such-fixture','--hotplug-seconds','0','--ready',str(ready)]
            result=subprocess.run(args,preexec_fn=lambda:os.close(1),capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(output.read_text())['status'],'observed')
            self.assertFalse(json.loads(ready.read_text())['initialDeviceAccessible'])
