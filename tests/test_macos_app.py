"""Packaging must retain the qualified native contract rather than invent state."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from artifact.inspection import verify_bundle
from artifact.macos_app import create_macos_app_plan, stage_bundle, stage_cage, tools_lock, verify_python_metadata
from cage.cli import main
from runtime.desktop_launch import DesktopError
from runtime.macos_launch import run_plan
from tests.test_macos_target import sealed


class MacOSAppTests(unittest.TestCase):
    def test_app_planning_preserves_cli_identity_and_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); bundle = sealed(root / 'bundles')
            with self.assertRaisesRegex(DesktopError, 'allow-host-access'):
                create_macos_app_plan(bundle)
            with patch('artifact.macos_app.download') as acquire, contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['export', 'macos-app', str(bundle), '--dry-run', '--allow-host-access',
                                       '--output', str(root / 'test.app'), '--macos-store', str(root / 'wine'),
                                       '--state-dir', str(root / 'state')]), 0)
                acquire.assert_not_called()
            plan = json.loads(out.getvalue())
            original = run_plan(bundle, store=root / 'wine', state_dir=root / 'state', allow_host_access=True)
            self.assertEqual(plan['config']['identity'], original['identity'])
            self.assertEqual(plan['contract'], original['contract'])
            self.assertEqual(plan['config']['stateParent'], str(root / 'state'))
            for name in ('test.app', 'wine', 'state'):
                self.assertFalse((root / name).exists())
            default = create_macos_app_plan(bundle, allow_host_access=True)
            self.assertIsNone(default['config']['runtimeStore']); self.assertIsNone(default['config']['stateParent'])

    def test_packaged_source_is_verified_and_launch_imports_without_host_cage(self):
        with tempfile.TemporaryDirectory() as td:
            # macOS tempfile uses /var -> /private/var. Real exports require a
            # canonical parent through build_lock; preserve that same boundary.
            root = Path(td).resolve(); bundle = sealed(root / 'bundles')
            (bundle / 'build/home').mkdir(); (bundle / 'build/home/private').write_text('must not package')
            copied = root / 'application'; stage_bundle(bundle, copied)
            self.assertTrue(verify_bundle(copied)['valid']); self.assertFalse((copied / 'build/home').exists())
            code = root / 'cage-code'; inventory = stage_cage(code)
            self.assertTrue(inventory)
            check = ('import sys,json;from pathlib import Path;'
                     'sys.path.insert(0,sys.argv[1]);from runtime.macos_launch import run_plan;'
                     'p=run_plan(sys.argv[2],allow_host_access=True);'
                     'print(json.dumps(p["identity"]))')
            result = subprocess.check_output([sys.executable, '-I', '-B', '-c', check, str(code), str(copied)],
                                             cwd=root, text=True)
            self.assertEqual(json.loads(result), run_plan(bundle, allow_host_access=True)['identity'])
            (copied / 'prefix/drive_c/settings.txt').write_text('changed')
            with self.assertRaises(DesktopError): create_macos_app_plan(copied, allow_host_access=True)

    def test_standalone_python_release_tag_and_bytes_are_bound_together(self):
        lock = tools_lock(); spec = lock['asset']
        release = {'id':lock['releaseId'], 'tag_name':lock['tag'], 'assets':[
            {'id':spec['id'], 'name':spec['name'], 'size':spec['size'], 'digest':'sha256:'+spec['sha256'],
             'browser_download_url':spec['url']}]}
        tag = {'type':'commit','sha':lock['sourceCommit']}
        verify_python_metadata(lock, release, tag)
        altered = copy.deepcopy(release); altered['assets'][0]['digest'] = 'sha256:'+'0'*64
        with self.assertRaises(DesktopError):verify_python_metadata(lock, altered, tag)
        with self.assertRaises(DesktopError):verify_python_metadata(lock, release, {**tag,'sha':'0'*40})
