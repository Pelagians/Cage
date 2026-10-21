"""Managed persistence wraps, rather than replaces, existing container launch."""
import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact.bundle import create_bundle
from artifact.oci import create_oci_export_plan, prepare_oci_build_context
from core.manifest import load_manifest
from runtime.container_state import managed_plan
from runtime.launcher import build_run_plan, RunError
from runtime.desktop_launch import DesktopError
from tests.bundle_fixtures import materialize_runnable_prefix

ROOT = Path(__file__).resolve().parents[1]


class ContainerUpdateTests(unittest.TestCase):
    def bundle(self, directory):
        manifest = load_manifest(ROOT / 'recipes/notepadplusplus-portable.cage.yaml')
        manifest = replace(manifest, runtime=replace(manifest.runtime,
                           image='example/wine@sha256:' + 'a' * 64, digest='a' * 64))
        bundle = create_bundle(manifest, Path(directory) / 'dist', dry_run=True)
        materialize_runnable_prefix(bundle, entrypoint=manifest.launch.entrypoint)
        return bundle

    def test_legacy_container_state_is_opt_in_and_dry_plan_does_not_write_state(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = self.bundle(td)
            state = Path(td) / 'state'
            plan = build_run_plan(bundle, engine='podman', state_dir=state, state_action='update')
            script = plan['container']['script']
            self.assertIn('container_state.py --plan-b64', script)
            encoded = script.strip().split()[-1]
            wrapped = base64.b64decode(encoded).decode()
            self.assertIn('export WINEPREFIX="$CAGE_MANAGED_PREFIX"', wrapped)
            self.assertNotIn('rm -rf "$WINEPREFIX"', wrapped)
            self.assertNotIn('cp -a "$CAGE_PREFIX_SOURCE"', wrapped)
            self.assertIn('cage-select-wine-graphics', wrapped)
            self.assertIn('exec wine ', wrapped)
            self.assertFalse(state.exists())
            self.assertTrue(any('/opt/cage-lifecycle' in part and ':ro' in part for part in plan['container']['argv']))
            # Default ephemeral/hosted path remains the original launch script.
            legacy = build_run_plan(bundle, engine='podman')['container']['script']
            self.assertIn('rm -rf "$WINEPREFIX"', legacy)
            self.assertNotIn('container_state.py', legacy)

    def test_oci_export_ships_same_manager_and_retains_legacy_launcher_setup(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = self.bundle(td)
            plan = create_oci_export_plan(bundle, tag='example/update-test')
            self.assertIn('managedState', plan)
            context = prepare_oci_build_context(bundle, plan, Path(td) / 'context')
            self.assertIn('container_state.py', (context / 'cage-app-launch').read_text())
            legacy = (context / 'lifecycle/legacy.sh').read_text()
            self.assertIn('CAGE_MANAGED_PREFIX', legacy)
            self.assertIn('_compatibility_env', legacy)
            self.assertIn('cage-select-wine-graphics', legacy)
            self.assertTrue((context / 'lifecycle/desktop_launch.py').is_file())

    def test_explicit_managed_desktop_reuses_native_startup_without_changing_hosted_defaults(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'DISPLAY': ':91'}):
            bundle = self.bundle(td)
            plan = build_run_plan(bundle, engine='podman', graphics='desktop', state_dir=Path(td) / 'state')
            argv = plan['container']['argv']
            self.assertIn('--entrypoint', argv)
            self.assertEqual(argv[-2:], ['-I', '/opt/cage-lifecycle/container_init.py'])
            hosted = build_run_plan(bundle, engine='podman', graphics='selkies', network='bridge')
            self.assertNotIn('--entrypoint', hosted['container']['argv'])
            exported = create_oci_export_plan(bundle, tag='example/desktop', graphics='desktop')
            self.assertIn('ENTRYPOINT ["/usr/bin/python3", "-I", "/opt/cage-lifecycle/container_init.py"]', exported['containerfile']['content'])
            context = prepare_oci_build_context(bundle, exported, Path(td) / 'context')
            self.assertTrue((context / 'lifecycle/container_init.py').is_file())

    def test_mutable_carriers_external_runners_and_unqualified_environment_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = self.bundle(td)
            path = bundle / 'metadata/graph.json'
            graph = json.loads(path.read_text())
            graph['runnerRuntime']['image'] = 'example/wine:mutable'
            path.write_text(json.dumps(graph))
            with self.assertRaisesRegex(DesktopError, 'digest-pinned'):
                managed_plan(bundle)
            graph['runnerRuntime']['image'] = 'example/wine@sha256:' + 'b' * 64
            graph['runnerRuntime']['launcher'] = 'umu'
            path.write_text(json.dumps(graph))
            with self.assertRaisesRegex(DesktopError, 'builtin Wine'):
                managed_plan(bundle)
            graph['runnerRuntime']['launcher'] = 'wine'
            graph['launch']['env'] = {'WINEPREFIX': '/somewhere/unsafe'}
            path.write_text(json.dumps(graph))
            with self.assertRaisesRegex(DesktopError, 'cannot be overridden'):
                managed_plan(bundle)


if __name__ == '__main__':
    unittest.main()
