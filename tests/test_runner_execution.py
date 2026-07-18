"""Tests for Phase 6G cached runner execution wiring."""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact.bundle import create_bundle
from builder.executor import execute_inside_container
from builder.pipeline import generate_build_script
from core.manifest import Manifest
from runtime.launcher import RunError, build_run_plan
from tests.bundle_fixtures import materialize_runnable_prefix


RUNNER_MANIFEST = {
    "schemaVersion": "cage.app/v0",
    "name": "runner-mounted-app",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "9.0", "runner": "pol-4.3"},
    "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
    "provenance": {"sources": []},
}


def _cfw_runtime():
    return {
        "id": "cfw-runtime-test",
        "url": "https://example.invalid/cfw-runtime-prefix.tar.gz",
        "evidenceUrl": "https://example.invalid/runtime.json",
        "manifestUrl": "https://example.invalid/cfw-runtime-manifest.json",
        "manifestSha256": "a" * 64,
        "wineImage": "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64,
        "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
    }


class RunnerExecutionBuildTests(unittest.TestCase):
    def test_build_script_uses_cached_runner_when_runner_bin_env_is_present(self):
        script = generate_build_script(Manifest.from_dict(RUNNER_MANIFEST))

        self.assertIn("CAGE_RUNNER_BIN", script)
        self.assertIn('export PATH="$CAGE_RUNNER_BIN:$PATH"', script)
        self.assertIn('export WINE="$CAGE_RUNNER_BIN/wine"', script)
        self.assertIn('Using cached Wine runner', script)

    def test_cfw_runtime_rejects_separate_cached_runner(self):
        manifest_data = {
            **RUNNER_MANIFEST,
            "runtime": {**RUNNER_MANIFEST["runtime"], "version": "11.0"},
            "modules": [{
                "type": "chocolatey",
                "install": {
                    "packages": [],
                    "runtimeArtifact": {
                        "id": "cfw-runtime-test",
                        "url": "https://example.invalid/cfw-runtime-prefix.tar.gz",
                        "evidenceUrl": "https://example.invalid/runtime.json",
                        "manifestUrl": "https://example.invalid/cfw-runtime-manifest.json",
                        "manifestSha256": "a" * 64,
                        "wineImage": "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64,
                        "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
                    },
                },
            }],
        }
        with self.assertRaisesRegex(Exception, "cannot use runtime.runner"):
            Manifest.from_dict(manifest_data)

    def test_cfw_runtime_rejects_cage_compatibility_mutation(self):
        manifest_data = {
            **RUNNER_MANIFEST,
            "runtime": {"provider": "wine", "version": "11.0"},
            "compatibility": {"windowsVersion": "win7"},
            "modules": [{
                "type": "chocolatey",
                "install": {"packages": [], "runtimeArtifact": _cfw_runtime()},
            }],
        }
        with self.assertRaisesRegex(Exception, "cannot declare Cage compatibility policy"):
            Manifest.from_dict(manifest_data)

    def test_cfw_runtime_rejects_compatibility_mutating_modules(self):
        for module in (
            {"type": "winetricks", "verbs": ["corefonts"]},
            {"type": "script", "command": "winecfg -v win7"},
            {"type": "containerfile", "instructions": ["RUN winetricks corefonts"]},
        ):
            manifest_data = {
                **RUNNER_MANIFEST,
                "runtime": {"provider": "wine", "version": "11.0"},
                "modules": [
                    {"type": "chocolatey", "install": {
                        "packages": [], "runtimeArtifact": _cfw_runtime(),
                    }},
                    module,
                ],
            }
            with self.subTest(module=module["type"]), self.assertRaisesRegex(
                Exception, "cannot combine with compatibility-mutating module"
            ):
                Manifest.from_dict(manifest_data)

    def test_cfw_runtime_rejects_mutable_or_mismatched_container_image(self):
        pinned_image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        manifest_data = {
            **RUNNER_MANIFEST,
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [{
                "type": "chocolatey",
                "install": {
                    "packages": [],
                    "runtimeArtifact": {
                        "id": "cfw-runtime-test",
                        "url": "https://example.invalid/cfw-runtime-prefix.tar.gz",
                        "evidenceUrl": "https://example.invalid/runtime.json",
                        "manifestUrl": "https://example.invalid/cfw-runtime-manifest.json",
                        "manifestSha256": "a" * 64,
                        "wineImage": pinned_image,
                        "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
                    },
                },
            }],
        }
        manifest = Manifest.from_dict(manifest_data)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bundle = create_bundle(manifest, tmp / "dist", dry_run=False)
            with self.assertRaisesRegex(RuntimeError, "does not match pinned CFW image"):
                execute_inside_container(
                    manifest,
                    bundle,
                    engine="podman",
                    image_ref="ghcr.io/pelagians/cage-wine:11.0",
                    workspace=tmp,
                )

    def test_cfw_build_container_receives_producer_declared_environment(self):
        manifest_data = {
            **RUNNER_MANIFEST,
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [{
                "type": "chocolatey",
                "install": {"packages": [], "runtimeArtifact": _cfw_runtime()},
            }],
        }
        manifest = Manifest.from_dict(manifest_data)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bundle = create_bundle(manifest, tmp / "dist", dry_run=False)

            class Completed:
                returncode = 1
                stdout = ""
                stderr = "expected test failure"

            with patch("builder.executor._run_container_command", return_value=Completed()) as run, \
                 patch("sys.stderr", io.StringIO()):
                execute_inside_container(manifest, bundle, engine="podman", workspace=tmp)

        argv = run.call_args.args[0]
        self.assertIn("WINEDLLOVERRIDES=", argv)

    def test_execute_inside_container_mounts_cached_runner_for_real_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            runner_dir = tmp / "cache" / "pol-4.3"
            (runner_dir / "bin").mkdir(parents=True)
            (runner_dir / "bin" / "wine").write_text("#!/bin/sh\n", encoding="utf-8")
            manifest = Manifest.from_dict(RUNNER_MANIFEST)
            bundle = create_bundle(manifest, tmp / "dist", dry_run=False)

            class Completed:
                returncode = 0
                stdout = "container ok"
                stderr = ""

            ensure_result = {
                "schemaVersion": "cage.runner-cache/v0",
                "status": "present",
                "cacheDir": str(tmp / "cache"),
                "runnerDir": str(runner_dir),
                "winePath": str(runner_dir / "bin" / "wine"),
                "runner": {"id": "pol-4.3"},
                "diagnostic": {"status": "missing-elf-interpreter"},
            }
            def fake_run(*_args, **_kwargs):
                materialize_runnable_prefix(
                    bundle,
                    entrypoint=RUNNER_MANIFEST["launch"]["entrypoint"],
                )
                return Completed()

            with patch("builder.executor.ensure_runner", return_value=ensure_result) as ensure_runner:
                with patch("builder.executor._run_container_command", side_effect=fake_run) as run, patch("sys.stderr", io.StringIO()):
                    result = execute_inside_container(
                        manifest,
                        bundle,
                        engine="podman",
                        image_ref="local/runtime:test",
                        timeout=5,
                        workspace=tmp,
                        runner_cache_dir=tmp / "cache",
                    )
                    script = (bundle / "build" / "run.sh").read_text(encoding="utf-8")

        self.assertTrue(result.success)
        ensure_runner.assert_called_once_with("pol-4.3", cache_dir=tmp / "cache")
        argv = run.call_args.args[0]
        self.assertIn(f"{runner_dir.resolve()}:/opt/cage-runner:ro,z", argv)
        self.assertIn("CAGE_RUNNER_BIN=/opt/cage-runner/bin", argv)
        self.assertIn("CAGE_RUNNER_ID=pol-4.3", argv)
        self.assertIn('export PATH="$CAGE_RUNNER_BIN:$PATH"', script)
        self.assertEqual(result.runner_cache["status"], "present")
        self.assertEqual(result.runner_cache["containerDir"], "/opt/cage-runner")


class RunnerExecutionRunPlanTests(unittest.TestCase):
    def test_run_plan_mounts_cached_runner_and_exports_runner_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            runner_dir = tmp / "cache" / "pol-4.3"
            (runner_dir / "bin").mkdir(parents=True)
            (runner_dir / "bin" / "wine").write_text("#!/bin/sh\n", encoding="utf-8")
            bundle = create_bundle(Manifest.from_dict(RUNNER_MANIFEST), tmp / "dist", dry_run=True)

            plan = build_run_plan(
                bundle,
                graphics="headless",
                engine="podman",
                runner_cache_dir=tmp / "cache",
            allow_non_runnable=True,
            )

        self.assertEqual(plan["runnerCache"]["status"], "present")
        self.assertEqual(plan["runnerCache"]["runnerId"], "pol-4.3")
        self.assertEqual(plan["runnerCache"]["containerDir"], "/opt/cage-runner")
        self.assertIn(f"{runner_dir.resolve()}:/opt/cage-runner:ro,z", plan["container"]["argv"])
        self.assertEqual(plan["container"]["environment"]["CAGE_RUNNER_BIN"], "/opt/cage-runner/bin")
        self.assertEqual(plan["container"]["environment"]["CAGE_RUNNER_ID"], "pol-4.3")
        self.assertIn('export PATH="$CAGE_RUNNER_BIN:$PATH"', plan["container"]["script"])

    def test_podman_run_plan_mounts_include_selinux_shared_relabel_option(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            runner_dir = tmp / "cache" / "pol-4.3"
            (runner_dir / "bin").mkdir(parents=True)
            (runner_dir / "bin" / "wine").write_text("#!/bin/sh\n", encoding="utf-8")
            bundle = create_bundle(Manifest.from_dict(RUNNER_MANIFEST), tmp / "dist", dry_run=True)

            plan = build_run_plan(
                bundle,
                graphics="headless",
                engine="podman",
                runner_cache_dir=tmp / "cache",
            allow_non_runnable=True,
            )

        self.assertEqual(plan["container"]["bundleMount"], f"{bundle.resolve()}:/opt/cage/bundle:ro,z")
        self.assertIn(f"{bundle.resolve()}:/opt/cage/bundle:ro,z", plan["container"]["argv"])
        self.assertIn(f"{runner_dir.resolve()}:/opt/cage-runner:ro,z", plan["container"]["argv"])

    def test_docker_run_plan_mounts_do_not_include_podman_selinux_option(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            runner_dir = tmp / "cache" / "pol-4.3"
            (runner_dir / "bin").mkdir(parents=True)
            (runner_dir / "bin" / "wine").write_text("#!/bin/sh\n", encoding="utf-8")
            bundle = create_bundle(Manifest.from_dict(RUNNER_MANIFEST), tmp / "dist", dry_run=True)

            plan = build_run_plan(
                bundle,
                graphics="headless",
                engine="docker",
                runner_cache_dir=tmp / "cache",
            allow_non_runnable=True,
            )

        self.assertEqual(plan["container"]["bundleMount"], f"{bundle.resolve()}:/opt/cage/bundle:ro")
        self.assertIn(f"{runner_dir.resolve()}:/opt/cage-runner:ro", plan["container"]["argv"])
        self.assertNotIn(f"{runner_dir.resolve()}:/opt/cage-runner:ro,z", plan["container"]["argv"])


    def test_catalog_runner_label_is_not_treated_as_downloadable_cache(self):
        plain_manifest = dict(RUNNER_MANIFEST)
        plain_manifest["runtime"] = {"provider": "wine", "version": "latest"}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bundle = create_bundle(Manifest.from_dict(plain_manifest), tmp / "dist", dry_run=True)
            plan = build_run_plan(
                bundle,
                graphics="headless",
                engine="podman",
                runner_cache_dir=tmp / "cache",
                require_runner=True,
            allow_non_runnable=True,
            )

        self.assertIsNone(plan["runnerCache"])
        self.assertNotIn("CAGE_RUNNER_BIN", plan["container"]["environment"])

    def test_run_plan_reports_missing_cached_runner_and_can_require_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bundle = create_bundle(Manifest.from_dict(RUNNER_MANIFEST), tmp / "dist", dry_run=True)

            plan = build_run_plan(
                bundle,
                graphics="headless",
                engine="podman",
                runner_cache_dir=tmp / "cache",
            allow_non_runnable=True,
            )
            with self.assertRaisesRegex(RunError, "cached runner is missing"):
                build_run_plan(
                    bundle,
                    graphics="headless",
                    engine="podman",
                    runner_cache_dir=tmp / "cache",
                    require_runner=True,
                allow_non_runnable=True,
                )

        self.assertEqual(plan["runnerCache"]["status"], "missing")
        self.assertNotIn("CAGE_RUNNER_BIN", plan["container"]["environment"])


if __name__ == "__main__":
    unittest.main()
