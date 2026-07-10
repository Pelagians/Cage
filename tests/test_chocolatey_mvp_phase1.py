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
from builder.executor import execute_inside_container
from builder.pipeline import generate_build_script
from cage.cli import build_parser, cmd_build
from core.manifest import Manifest


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
        self.assertIn("mv \"$CAGE_PREFIX_PARTIAL\" \"$CAGE_PREFIX_FINAL\"", script)
        self.assertLess(script.index("Verifying launch executable"), script.index("mv \"$CAGE_PREFIX_PARTIAL\""))

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
