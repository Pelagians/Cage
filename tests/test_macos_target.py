"""Native target boundaries and reuse of the existing sealed state lifecycle."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact.bundle import create_bundle, update_bundle_execution_metadata
from artifact.desktop import seal_desktop_bundle
from artifact.inspection import verify_bundle
from artifact.macos import validate_recipe, launch_plan
from builder.macos import execute_module
from cage.cli import main
from core.manifest import load_manifest, Manifest, ManifestError
from runtime.desktop_launch import DesktopError, digest_json, inventory_tree, prepare_generation, plan_identity
from runtime.macos import runtime_target, verify_runtime, ensure_runtime
from runtime.macos_launch import run_plan
from runtime.providers import resolve_runtime, resolve_image

ROOT = Path(__file__).resolve().parents[1]


def manifest():
    return load_manifest(ROOT / 'recipes/notepadplusplus-portable-macos.cage.yaml')


def sealed(output):
    m = manifest(); target = runtime_target()
    bundle = create_bundle(m, output, dry_run=False)
    (bundle / 'metadata/execution-target.json').write_text(json.dumps(target))
    prefix = bundle / 'prefix'
    (prefix / 'dosdevices').mkdir(); (prefix / 'dosdevices/c:').symlink_to('../drive_c')
    app = prefix / 'drive_c/Program Files/Notepad++/notepad++.exe'; app.parent.mkdir(parents=True)
    data = bytearray(128); data[:2] = b'MZ'; data[60:64] = (64).to_bytes(4, 'little'); data[64:70] = b'PE\0\0\x64\x86'
    app.write_bytes(data); (prefix / 'drive_c/settings.txt').write_text('seed')
    receipt = seal_desktop_bundle(bundle, target, {'payloadDigest': target['payloadDigest']})
    (bundle / 'metadata/macos-launch.json').write_text(json.dumps(launch_plan(m, receipt['seedDigest'])))
    (bundle / 'metadata/prefix-materialization.json').write_text(json.dumps({
        'schemaVersion': 'cage.prefix-materialization/v0', 'completed': True, 'fileCount': 2, 'byteSize': 132}))
    update_bundle_execution_metadata(bundle, state='runnable', runnable=True, materialized_prefix=True, has_default_launch=True)
    return bundle


class MacOSTargetTests(unittest.TestCase):
    def test_explicit_darwin_identity_does_not_select_a_linux_carrier(self):
        m = manifest(); binding = resolve_runtime(m.runtime)
        self.assertEqual(binding.architecture, 'arm64')
        self.assertEqual(binding.execution_target['os'], 'darwin')
        self.assertIsNone(binding.oci_image)
        self.assertIsNone(resolve_image('wine-macos', '11.20'))
        from runtime.arm64ec import runtime_target as linux
        self.assertEqual(linux()['os'], 'linux')
        self.assertEqual(linux()['architecture'], 'aarch64')

    def test_build_dry_run_is_pure_on_linux(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with contextlib.redirect_stdout(io.StringIO()) as out, patch('runtime.macos.ensure_runtime') as acquire:
                self.assertEqual(main(['build', str(ROOT / 'recipes/notepadplusplus-portable-macos.cage.yaml'),
                                       '--target', 'macos', '--dry-run', '--output', str(root / 'out'),
                                       '--macos-store', str(root / 'runtime')]), 0)
                acquire.assert_not_called()
            self.assertEqual(json.loads(out.getvalue())['target']['graphics'], 'winemac')
            self.assertEqual(list(root.iterdir()), [])

    def test_native_provider_requires_target_host_access_and_supported_modules(self):
        m = manifest()
        self.assertEqual(validate_recipe(m)['provider'], 'wine-macos')
        for change in ({'network': 'none'}, {'wineGraphics': 'xwayland'}, {'version': 'latest'}, {'image': 'linux:latest'}):
            payload = m.to_dict(); payload['runtime'].update(change)
            with self.assertRaises(ManifestError):
                Manifest.from_dict(payload)
        payload = m.to_dict(); payload['compatibility'] = {'env': {'FEX_TSOENABLED': '0'}}
        with self.assertRaisesRegex(DesktopError, 'runtime-owned'):
            validate_recipe(Manifest.from_dict(payload))
        payload = m.to_dict(); payload['compatibility'] = {'graphics': {'backend': 'wined3d'}}
        with self.assertRaisesRegex(DesktopError, 'graphics overrides'):
            validate_recipe(Manifest.from_dict(payload))
        payload = m.to_dict(); payload['launch']['env'] = {'GRAPHICS_BACKEND': 'dxvk'}
        with self.assertRaisesRegex(DesktopError, 'runtime-owned'):
            validate_recipe(Manifest.from_dict(payload))
        payload = m.to_dict(); payload['modules'] = [{'type': 'check', 'command': {'run': 'echo unsafe', 'exitCode': 0}}]
        with self.assertRaises((DesktopError, ManifestError)):
            validate_recipe(Manifest.from_dict(payload))

    def test_runtime_mismatch_retains_cache_and_refuses_acquisition_on_linux(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); runtime = root / 'fixture'; runtime.mkdir(); f = runtime / 'wine'; f.write_bytes(b'original')
            target = dict(runtime_target(), runtimeDirectory='fixture', payloadDigest=digest_json(inventory_tree(runtime)))
            with patch('runtime.macos.runtime_target', return_value=target):
                self.assertEqual(verify_runtime(root), runtime)
                f.write_bytes(b'changed')
                with self.assertRaisesRegex(DesktopError, 'inventory mismatch'):
                    verify_runtime(root)
                self.assertEqual(f.read_bytes(), b'changed')
            with patch('runtime.macos.platform.system', return_value='Linux'), patch('runtime.macos.provenance') as acquire:
                with self.assertRaises(DesktopError): ensure_runtime(root / 'new')
                acquire.assert_not_called(); self.assertFalse((root / 'new').exists())

    def test_sealed_bundle_tamper_and_dry_run_do_not_create_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bundle = sealed(root / 'bundles')
            self.assertTrue(verify_bundle(bundle)['valid'], verify_bundle(bundle)['errors'])
            with self.assertRaisesRegex(DesktopError, 'allow-host-access'):
                run_plan(bundle, state_dir=root / 'state')
            plan = run_plan(bundle, state_dir=root / 'state', allow_host_access=True)
            self.assertEqual(plan['contract']['target']['os'], 'darwin'); self.assertFalse((root / 'state').exists())
            path = bundle / 'metadata/macos-launch.json'; payload = json.loads(path.read_text()); payload['environment']['FEX_TSOENABLED'] = '0'
            path.write_text(json.dumps(payload))
            self.assertFalse(verify_bundle(bundle)['valid'])
            with self.assertRaises(DesktopError): run_plan(bundle, state_dir=root / 'state', allow_host_access=True)
            self.assertFalse((root / 'state').exists())

    def test_existing_lifecycle_preserves_documents_and_refuses_different_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); bundle = sealed(root / 'bundles')
            receipt = json.loads((bundle / 'metadata/desktop-build.json').read_text())
            plan = launch_plan(manifest(), receipt['seedDigest']); identity = plan_identity(plan)
            state = root / 'state'; state.mkdir()
            prefix, pending = prepare_generation(bundle / 'prefix', receipt['inventory'], state, identity, plan, None)
            self.assertIsNone(pending)
            (prefix / 'drive_c/document.txt').write_text('retain current document')
            before = (state / 'state.json').read_bytes()
            self.assertEqual(prepare_generation(bundle / 'prefix', receipt['inventory'], state, identity, plan, None)[0], prefix)
            changed = copy.deepcopy(plan); changed['environment']['APPLICATION_FLAG'] = 'different'
            with self.assertRaises(DesktopError):
                prepare_generation(bundle / 'prefix', receipt['inventory'], state, plan_identity(changed), changed, None)
            self.assertEqual((state / 'state.json').read_bytes(), before)
            self.assertEqual((prefix / 'drive_c/document.txt').read_text(), 'retain current document')

    def test_native_file_operations_cannot_follow_a_prefix_link_to_host_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prefix = root / 'prefix'; (prefix / 'drive_c').mkdir(parents=True)
            outside = root / 'outside'; outside.mkdir(); (outside / 'keep').write_text('retain')
            (prefix / 'drive_c/escape').symlink_to(outside, target_is_directory=True)
            source = root / 'inputs'; source.mkdir(); (source / 'file').write_text('new')
            operation = {'kind': 'copy-tree', 'metadata': {'mappings': [{'source': 'file', 'target': 'C:/escape/keep'}]}}
            with self.assertRaises(DesktopError):
                execute_module(operation, prefix, source, None, {}, root, root / 'log')
            self.assertEqual((outside / 'keep').read_text(), 'retain')
