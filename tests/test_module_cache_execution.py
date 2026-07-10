"""Tests for module payload cache wiring."""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact.bundle import create_bundle
from builder.executor import execute_inside_container
from cage.cli import build_parser
from compat.evidence import run_compat_test
from core.manifest import Manifest
from tests.bundle_fixtures import materialize_runnable_prefix


MANIFEST = {
    "schemaVersion": "cage.app/v0",
    "name": "module-cache-app",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "latest"},
    "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
    "provenance": {"sources": []},
}


class ModuleCacheExecutionTests(unittest.TestCase):
    def test_execute_inside_container_mounts_module_cache_for_real_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cache = tmp / "module-cache"
            manifest = Manifest.from_dict(MANIFEST)
            bundle = create_bundle(manifest, tmp / "dist", dry_run=False)

            class Completed:
                returncode = 0
                stdout = "container ok"
                stderr = ""

            def fake_run(*_args, **_kwargs):
                materialize_runnable_prefix(
                    bundle,
                    entrypoint=MANIFEST["launch"]["entrypoint"],
                )
                return Completed()

            with patch("builder.executor._run_container_command", side_effect=fake_run) as run, patch("sys.stderr", io.StringIO()):
                result = execute_inside_container(
                    manifest,
                    bundle,
                    engine="podman",
                    image_ref="local/runtime:test",
                    timeout=5,
                    workspace=tmp,
                    module_cache_dir=cache,
                )

        self.assertTrue(result.success)
        argv = run.call_args.args[0]
        self.assertIn(f"{cache.resolve()}:/opt/cage-module-cache:z", argv)
        self.assertIn("CAGE_MODULE_CACHE_DIR=/opt/cage-module-cache", argv)
        self.assertEqual(result.module_cache["containerDir"], "/opt/cage-module-cache")

    def test_execute_inside_container_normalizes_docker_emulation_to_podman(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cache = tmp / "module-cache"
            manifest = Manifest.from_dict(MANIFEST)
            bundle = create_bundle(manifest, tmp / "dist", dry_run=False)

            class Completed:
                returncode = 0
                stdout = "container ok"
                stderr = ""

            with (
                patch("builder.executor._find_engine", return_value="podman") as find_engine,
                patch("builder.executor._run_container_command", return_value=Completed()) as run,
                patch("sys.stderr", io.StringIO()),
            ):
                result = execute_inside_container(
                    manifest,
                    bundle,
                    engine="docker",
                    image_ref="local/runtime:test",
                    timeout=5,
                    workspace=tmp,
                    module_cache_dir=cache,
                )

        find_engine.assert_called_once_with("docker")
        self.assertEqual(result.engine, "podman")
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "podman")
        self.assertIn(f"{bundle.resolve()}:/opt/cage:z", argv)
        self.assertIn(f"{cache.resolve()}:/opt/cage-module-cache:z", argv)


    def test_execute_inside_container_uses_build_network_without_changing_runtime_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            data = dict(MANIFEST)
            data["runtime"] = {"provider": "wine", "version": "latest", "network": "none"}
            data["build"] = {"network": "host"}
            manifest = Manifest.from_dict(data)
            bundle = create_bundle(manifest, tmp / "dist", dry_run=False)

            class Completed:
                returncode = 0
                stdout = "container ok"
                stderr = ""

            def fake_run(*_args, **_kwargs):
                materialize_runnable_prefix(
                    bundle,
                    entrypoint=MANIFEST["launch"]["entrypoint"],
                )
                return Completed()

            with patch("builder.executor._run_container_command", side_effect=fake_run) as run, patch("sys.stderr", io.StringIO()):
                execute_inside_container(
                    manifest,
                    bundle,
                    engine="docker",
                    image_ref="local/runtime:test",
                    timeout=5,
                    workspace=tmp,
                )

        argv = run.call_args.args[0]
        self.assertIn("--net", argv)
        self.assertEqual(argv[argv.index("--net") + 1], "host")

    def test_build_and_compat_cli_accept_module_cache_dir(self):
        parser = build_parser()

        build_args = parser.parse_args([
            "build", "examples/vscode-choco-vnc.cage.yaml", "--module-cache-dir", "/tmp/cage-modules"
        ])
        compat_args = parser.parse_args([
            "compat", "test", "examples/vscode-choco-vnc.cage.yaml", "--module-cache-dir", "/tmp/cage-modules"
        ])

        self.assertEqual(build_args.module_cache_dir, "/tmp/cage-modules")
        self.assertEqual(compat_args.module_cache_dir, "/tmp/cage-modules")

    def test_compat_real_build_propagates_module_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest_path = root / "recipe.cage.json"
            manifest_path.write_text(__import__("json").dumps(MANIFEST), encoding="utf-8")
            cache = root / "module-cache"

            def fake_execute(manifest, bundle_path, *, engine, image_ref, timeout, workspace, runner_cache_dir=None, module_cache_dir=None, stop_before=None):
                from builder.executor import BuildResult
                self.assertEqual(Path(module_cache_dir), cache)
                return BuildResult(
                    success=True,
                    bundle_path=str(bundle_path),
                    runtime_provider=manifest.runtime.provider,
                    runtime_version=manifest.runtime.version,
                    image_ref=image_ref or "local/runtime:test",
                    engine=engine or "podman",
                    module_cache={"containerDir": "/opt/cage-module-cache"},
                )

            with patch("compat.evidence.execute_inside_container", side_effect=fake_execute):
                result = run_compat_test(
                    manifest_path,
                    output_dir=root / "dist",
                    workspace=root,
                    mode="build",
                    module_cache_dir=cache,
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["build"]["execution"]["moduleCache"]["containerDir"], "/opt/cage-module-cache")


if __name__ == "__main__":
    unittest.main()
