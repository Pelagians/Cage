"""Regression tests for the Chocolatey MVP Phase 1 artifact contract."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact.bundle import create_bundle
from artifact.inspection import verify_bundle
from artifact.oci import OCIExportError, create_oci_export_plan
from builder.executor import BuildResult, execute_inside_container
from builder.pipeline import generate_build_script
from cage.cli import build_parser, cmd_build
from core.manifest import Manifest
from runtime.launcher import build_run_plan
from tests.bundle_fixtures import materialize_runnable_prefix


APP = {
    "schemaVersion": "cage.app/v0",
    "name": "phase1-app",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "11.0", "network": "none"},
    "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
    "provenance": {"sources": []},
}


def _claim_runnable(bundle: Path) -> None:
    status_path = bundle / "metadata/status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({
        "state": "build-passed",
        "dryRun": False,
        "runnable": True,
        "materializedPrefix": True,
        "hasDefaultLaunch": True,
    })
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")


class CanonicalPrefixScriptTests(unittest.TestCase):
    def test_build_script_atomically_promotes_only_bundle_prefix(self):
        script = generate_build_script(Manifest.from_dict(APP))

        self.assertNotIn("/opt/cage/rootfs", script)
        self.assertIn("/opt/cage/prefix.partial", script)
        self.assertIn("/opt/cage/prefix", script)
        self.assertIn("CAGE_PREFIX_PARTIAL", script)
        self.assertIn('rm -f "$WINEPREFIX/dosdevices/z:"', script)
        self.assertLess(script.index('rm -f "$WINEPREFIX/dosdevices/z:"'), script.index('cp -a "$WINEPREFIX/." "$CAGE_PREFIX_PARTIAL/"'))
        self.assertIn("mv \"$CAGE_PREFIX_PARTIAL\" \"$CAGE_PREFIX_FINAL\"", script)
        self.assertLess(script.index("Verifying launch executable"), script.index("mv \"$CAGE_PREFIX_PARTIAL\""))

    def test_seeded_prefix_skips_producer_owned_wineboot_lifecycle(self):
        data = {
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": []}}],
        }
        script = generate_build_script(Manifest.from_dict(data))

        self.assertIn('Phase 1: Adopting prepared Wine prefix', script)
        self.assertIn('Prepared prefix adopted; skipping producer-owned wineboot lifecycle', script)
        self.assertNotIn('wine wineboot -u', script)
        self.assertNotIn('wine wineboot --init', script)

    def test_unseeded_prefix_runs_wineboot_init_and_retains_its_failure_boundary(self):
        script = generate_build_script(Manifest.from_dict(APP))

        self.assertIn('wineboot_log="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/wineboot.log"', script)
        self.assertIn('wineboot_rc="$?"', script)
        self.assertIn('wine wineboot --init', script)
        self.assertIn('wineboot --init failed with exit code $wineboot_rc', script)

    def test_launch_values_are_shell_quoted_in_generated_script(self):
        data = dict(APP)
        data["launch"] = {
            "entrypoint": "C:/Program Files/App/$(touch /tmp/cage-injected).exe",
            "args": ["$(touch /tmp/cage-args-injected)"],
        }

        script = generate_build_script(Manifest.from_dict(data))

        self.assertNotIn('echo "C:/Program Files/App/$(touch', script)
        self.assertNotIn('echo "  Args: $(touch', script)
        self.assertIn("'C:/Program Files/App/$(touch /tmp/cage-injected).exe'", script)
        self.assertIn("'$(touch /tmp/cage-args-injected)'", script)


class PrefixRunnabilityTests(unittest.TestCase):
    def test_placeholder_prefix_cannot_be_marked_runnable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            _claim_runnable(bundle)

            result = verify_bundle(bundle)

        self.assertTrue(result["valid"])
        self.assertFalse(result["runnable"])
        self.assertIn("prefix-materialization", {check["id"] for check in result["runnabilityChecks"]})

    def test_missing_launch_executable_prevents_runnable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            (bundle / "prefix/drive_c/.keep").unlink()
            (bundle / "prefix/drive_c/windows").mkdir()
            (bundle / "prefix/drive_c/windows/system.reg").write_text("baseline", encoding="utf-8")
            (bundle / "metadata/prefix-materialization.json").write_text(
                json.dumps({
                    "schemaVersion": "cage.prefix-materialization/v0",
                    "completed": True,
                    "fileCount": 1,
                    "byteSize": 8,
                }),
                encoding="utf-8",
            )
            _claim_runnable(bundle)

            result = verify_bundle(bundle)

        self.assertTrue(result["valid"])
        self.assertFalse(result["runnable"])
        launch_check = next(check for check in result["runnabilityChecks"] if check["id"] == "launch-executable")
        self.assertFalse(launch_check["ok"])


class ExecutorVerificationTests(unittest.TestCase):
    def test_container_exit_zero_without_materialized_prefix_fails_verification(self):
        manifest = Manifest.from_dict(APP)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=False)

            class Completed:
                returncode = 0
                stdout = "container exited zero without exporting a prefix"
                stderr = ""

            with patch("builder.executor._run_container_command", return_value=Completed()), patch("sys.stderr", io.StringIO()):
                result = execute_inside_container(
                    manifest,
                    bundle,
                    engine="docker",
                    image_ref="local/runtime:test",
                    timeout=5,
                    workspace=tmp,
                )

            status = json.loads((bundle / "metadata/status.json").read_text(encoding="utf-8"))

        self.assertFalse(result.success)
        self.assertEqual(status["state"], "verification-failed")
        self.assertFalse(status["runnable"])
        self.assertIn("materialized prefix", result.error or "")


class OCIExportGateTests(unittest.TestCase):
    def test_oci_export_rejects_structurally_valid_non_runnable_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)

            with self.assertRaisesRegex(OCIExportError, "not runnable"):
                create_oci_export_plan(bundle, tag="phase1-app:test")


class BuildSourcePreflightTests(unittest.TestCase):
    def test_cfw_launch_cannot_override_producer_environment(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        runtime = {
            "id": "cfw-runtime-test",
            "url": "https://example.invalid/runtime.tar.gz",
            "evidenceUrl": "https://example.invalid/runtime.json",
            "manifestUrl": "https://example.invalid/manifest.json",
            "manifestSha256": "c" * 64,
            "wineImage": image,
            "wineVersions": ["wine-11.0"],
            "environment": {"WINEDLLOVERRIDES": ""},
        }
        data = {
            **APP,
            "launch": {
                **APP["launch"],
                "env": {"WINEDLLOVERRIDES": "mscoree=n"},
            },
            "modules": [{
                "type": "chocolatey",
                "install": {"packages": [], "runtimeArtifact": runtime},
            }],
        }
        with self.assertRaisesRegex(Exception, "producer-owned environment"):
            Manifest.from_dict(data)

    def test_cfw_build_uses_pinned_image_for_execution_graph_and_oci_base(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        data = {
            **APP,
            "modules": [{"type": "chocolatey", "install": {
                "packages": [],
                "runtimeArtifact": {
                    "id": "cfw-runtime-test",
                    "url": "https://example.invalid/runtime.tar.gz",
                    "evidenceUrl": "https://example.invalid/runtime.json",
                    "manifestUrl": "https://example.invalid/manifest.json",
                    "manifestSha256": "c" * 64,
                    "wineImage": image,
                    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
                },
            }}],
        }
        manifest = Manifest.from_dict(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "dist"
            args = build_parser().parse_args([
                "build", str(root / "recipe.cage.yaml"),
                "--output", str(output), "--workspace", str(root), "--engine", "docker",
            ])
            failed = BuildResult(
                success=False,
                bundle_path=str(output / "phase1-app-1.0.0"),
                runtime_provider="wine",
                runtime_version="11.0",
                image_ref=image,
                engine="docker",
                exit_code=1,
            )
            with patch("cage.cli.load_manifest", return_value=manifest), \
                 patch("cage.cli.execute_inside_container", return_value=failed) as execute, \
                 patch("cage.cli.build_oci_image", return_value={"outputTag": "phase1-app:test"}) as oci, \
                 patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                rc = cmd_build(args)
            bundle = output / "phase1-app-1.0.0"
            graph = json.loads((bundle / "metadata/graph.json").read_text(encoding="utf-8"))
            runtime = json.loads((bundle / "runtime/runtime.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 1)
        self.assertEqual(execute.call_args.kwargs["image_ref"], image)
        self.assertEqual(oci.call_args.args[1], image)
        self.assertEqual(graph["builderRuntime"]["image"], image)
        self.assertEqual(graph["runnerRuntime"]["image"], image)
        self.assertEqual(graph["builderRuntime"]["environment"], {"WINEDLLOVERRIDES": ""})
        self.assertEqual(graph["runnerRuntime"]["environment"], {"WINEDLLOVERRIDES": ""})
        self.assertEqual(runtime["ociImage"], image)
        self.assertEqual(runtime["environment"], {"WINEDLLOVERRIDES": ""})

    def test_cfw_environment_reaches_run_plan_and_oci_export(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        data = {
            **APP,
            "modules": [{"type": "chocolatey", "install": {
                "packages": [],
                "runtimeArtifact": {
                    "id": "cfw-runtime-test",
                    "url": "https://example.invalid/runtime.tar.gz",
                    "evidenceUrl": "https://example.invalid/runtime.json",
                    "manifestUrl": "https://example.invalid/manifest.json",
                    "manifestSha256": "c" * 64,
                    "wineImage": image,
                    "wineVersions": ["wine-11.0"],
                    "environment": {"WINEDLLOVERRIDES": ""},
                },
            }}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=False)
            materialize_runnable_prefix(
                bundle,
                entrypoint=APP["launch"]["entrypoint"],
                chocolatey=True,
            )
            run_plan = build_run_plan(bundle, engine="podman")
            oci_plan = create_oci_export_plan(bundle, tag="phase1-app:test")

        self.assertEqual(run_plan["container"]["environment"]["WINEDLLOVERRIDES"], "")
        self.assertIn("WINEDLLOVERRIDES=", run_plan["container"]["argv"])
        self.assertEqual(oci_plan["runtime"]["environment"], {"WINEDLLOVERRIDES": ""})
        self.assertIn('ENV WINEDLLOVERRIDES=""', oci_plan["containerfile"]["content"])

    def test_failed_source_preflight_writes_evidence_and_skips_container(self):
        data = dict(APP)
        data["modules"] = [{
            "type": "portable",
            "source": "inputs/missing-app.zip",
            "target": "C:/Program Files/App",
        }]
        manifest = Manifest.from_dict(data)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "dist"
            args = build_parser().parse_args([
                "build",
                str(root / "recipe.cage.yaml"),
                "--output",
                str(output),
                "--workspace",
                str(root),
                "--engine",
                "docker",
            ])
            with patch("cage.cli.load_manifest", return_value=manifest), \
                 patch("cage.cli.execute_inside_container") as execute, \
                 patch("sys.stdout", io.StringIO()), \
                 patch("sys.stderr", io.StringIO()):
                rc = cmd_build(args)

            bundle = output / "phase1-app-1.0.0"
            integrity = json.loads((bundle / "metadata/source-integrity.json").read_text(encoding="utf-8"))
            policy = json.loads((bundle / "metadata/source-policy.json").read_text(encoding="utf-8"))
            status = json.loads((bundle / "metadata/status.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 1)
        execute.assert_not_called()
        self.assertFalse(integrity["valid"])
        self.assertFalse(policy["valid"])
        self.assertEqual(status["state"], "source-failed")
        self.assertFalse(status["runnable"])


if __name__ == "__main__":
    unittest.main()
