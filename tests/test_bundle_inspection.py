"""Tests for Cage bundle inspect/verify commands."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact.bundle import create_bundle
from artifact.inspection import inspect_bundle, verify_bundle
from core.manifest import Manifest


VALID = {
    "schemaVersion": "cage.app/v0",
    "name": "sample",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "9.0"},
    "modules": [
        {"type": "winetricks", "verbs": ["corefonts"]},
        {"type": "portable", "source": "file://app.zip", "target": "C:/Program Files/App"},
    ],
    "launch": {
        "entrypoint": "C:/Program Files/App/App.exe",
        "args": [],
        "env": {},
        "workingDirectory": "C:/Program Files/App",
    },
    "provenance": {"sources": []},
}


class BundleInspectionTests(unittest.TestCase):

    def _bundle(self, tmp: str) -> Path:
        return create_bundle(Manifest.from_dict(VALID), Path(tmp), dry_run=True)

    def test_inspect_bundle_returns_runtime_graph_and_file_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            summary = inspect_bundle(bundle)

        self.assertEqual(summary["schemaVersion"], "cage.bundle-inspection/v0")
        self.assertEqual(summary["application"], {"name": "sample", "version": "1.0.0"})
        self.assertEqual(summary["runtime"]["runner"]["image"], "ghcr.io/pelagians/cage-wine:9.0")
        self.assertEqual(summary["graph"]["schemaVersion"], "cage.execution-graph/v0")
        self.assertEqual(summary["graph"]["nodes"], 10)
        self.assertEqual(summary["graph"]["edges"], 11)
        self.assertTrue(summary["files"]["metadata/graph.json"]["exists"])
        self.assertTrue(summary["provenance"]["dryRun"])

    def test_verify_bundle_accepts_valid_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            result = verify_bundle(bundle)

        self.assertEqual(result["schemaVersion"], "cage.bundle-verification/v0")
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(any(check["id"] == "required-files" and check["ok"] for check in result["checks"]))
        self.assertTrue(any(check["id"] == "graph-runtime-match" and check["ok"] for check in result["checks"]))

    def test_verify_bundle_rejects_runtime_image_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            graph_path = bundle / "metadata" / "graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["runnerRuntime"]["image"] = "ghcr.io/pelagians/cage-wine:tampered"
            graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

            result = verify_bundle(bundle)

        self.assertFalse(result["valid"])
        check = next(check for check in result["checks"] if check["id"] == "graph-runtime-match")
        self.assertFalse(check["ok"])
        self.assertIn("image", "; ".join(result["errors"]))

    def test_verify_bundle_rejects_coherent_runtime_image_tampering_against_cfw_pin(self):
        pinned = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        tampered = "ghcr.io/pelagians/cage-wine@sha256:" + "e" * 64
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "cfw-bundle",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [{"type": "chocolatey", "install": {
                "packages": [],
                "runtimeArtifact": {
                    "id": "cfw-runtime-test",
                    "url": "https://example.invalid/runtime.tar.gz",
                    "evidenceUrl": "https://example.invalid/runtime.json",
                    "manifestUrl": "https://example.invalid/manifest.json",
                    "manifestSha256": "c" * 64,
                    "wineImage": pinned,
                    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
                },
            }}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            runtime_path = bundle / "runtime/runtime.json"
            graph_path = bundle / "metadata/graph.json"
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            runtime["ociImage"] = tampered
            runtime["digest"] = "e" * 64
            for key in ("builderRuntime", "runnerRuntime"):
                graph[key]["image"] = tampered
                graph[key]["ociImage"] = tampered
                graph[key]["digest"] = "e" * 64
            runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
            graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

            result = verify_bundle(bundle)

        self.assertFalse(result["valid"])
        check = next(check for check in result["checks"] if check["id"] == "cfw-runtime-trust-root")
        self.assertFalse(check["ok"])

    def test_verify_bundle_rejects_coherent_runtime_environment_tampering(self):
        pinned = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "cfw-environment",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [{"type": "chocolatey", "install": {
                "packages": [],
                "runtimeArtifact": {
                    "id": "cfw-runtime-test",
                    "url": "https://example.invalid/runtime.tar.gz",
                    "evidenceUrl": "https://example.invalid/runtime.json",
                    "manifestUrl": "https://example.invalid/manifest.json",
                    "manifestSha256": "c" * 64,
                    "wineImage": pinned,
                    "wineVersions": ["wine-11.0"],
                    "environment": {"WINEDLLOVERRIDES": ""},
                },
            }}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            runtime_path = bundle / "runtime/runtime.json"
            graph_path = bundle / "metadata/graph.json"
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            runtime["environment"] = {"WINEDLLOVERRIDES": "tampered"}
            graph["builderRuntime"]["environment"] = {"WINEDLLOVERRIDES": "tampered"}
            graph["runnerRuntime"]["environment"] = {"WINEDLLOVERRIDES": "tampered"}
            runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
            graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

            result = verify_bundle(bundle)

        self.assertFalse(result["valid"])
        check = next(check for check in result["checks"] if check["id"] == "cfw-runtime-trust-root")
        self.assertFalse(check["ok"])

    def test_verify_bundle_rejects_graph_launch_environment_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            graph_path = bundle / "metadata/graph.json"
            launch_path = bundle / "launch/entrypoint.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            launch = json.loads(launch_path.read_text(encoding="utf-8"))
            graph["launch"]["env"] = {"WINEDLLOVERRIDES": "mscoree=n"}
            launch["env"] = {"WINEDLLOVERRIDES": "mscoree=n"}
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            launch_path.write_text(json.dumps(launch), encoding="utf-8")
            result = verify_bundle(bundle)

        self.assertFalse(result["valid"])
        check = next(check for check in result["checks"] if check["id"] == "launch-match")
        self.assertFalse(check["ok"])

    def test_default_cfw_profile_serializes_trust_root_and_rejects_coherent_tampering(self):
        pinned = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        artifact = {
            "id": "cfw-runtime-default",
            "url": "https://example.invalid/runtime.tar.gz",
            "evidenceUrl": "https://example.invalid/runtime.json",
            "manifestUrl": "https://example.invalid/manifest.json",
            "manifestSha256": "c" * 64,
            "wineImage": pinned,
            "wineVersions": ["wine-11.0"],
            "environment": {"WINEDLLOVERRIDES": ""},
        }
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "default-cfw",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [{"type": "chocolatey", "install": {"packages": []}}],
        }
        with patch("core.modules.chocolatey.DEFAULT_CFW_RUNTIME_ARTIFACT", artifact), \
             tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            serialized = json.loads((bundle / "manifest.cage.json").read_text(encoding="utf-8"))
            self.assertEqual(serialized["modules"][0]["install"]["runtimeArtifact"], artifact)
            runtime_path = bundle / "runtime/runtime.json"
            graph_path = bundle / "metadata/graph.json"
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            tampered = "ghcr.io/pelagians/cage-wine@sha256:" + "e" * 64
            runtime.update({"ociImage": tampered, "digest": "e" * 64})
            for key in ("builderRuntime", "runnerRuntime"):
                graph[key].update({"image": tampered, "ociImage": tampered, "digest": "e" * 64})
            runtime_path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
            graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

            result = verify_bundle(bundle)

        self.assertFalse(result["valid"])

    def test_missing_cfw_release_is_valid_only_as_non_runnable_dry_run_placeholder(self):
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "missing-cfw",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [{"type": "chocolatey", "install": {"packages": []}}],
        }
        for dry_run, expected_valid in ((True, True), (False, False)):
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as tmp:
                bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=dry_run)
                result = verify_bundle(bundle)
                self.assertEqual(result["valid"], expected_valid)
                self.assertFalse(result["runnable"])

    def test_verify_bundle_rejects_missing_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            (bundle / "metadata" / "graph.json").unlink()
            result = verify_bundle(bundle)

        self.assertFalse(result["valid"])
        self.assertIn("missing required file: metadata/graph.json", result["errors"])

    def test_cli_bundle_inspect_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            inspect_proc = subprocess.run(
                [sys.executable, "cmd/cage.py", "bundle", "inspect", str(bundle)],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(inspect_proc.returncode, 0, inspect_proc.stderr)
            summary = json.loads(inspect_proc.stdout)
            self.assertEqual(summary["application"]["name"], "sample")

            verify_proc = subprocess.run(
                [sys.executable, "cmd/cage.py", "bundle", "verify", str(bundle)],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(verify_proc.returncode, 0, verify_proc.stderr)
            self.assertTrue(json.loads(verify_proc.stdout)["valid"])

    def test_cli_bundle_verify_exits_nonzero_for_invalid_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            (bundle / "metadata" / "graph.json").unlink()
            proc = subprocess.run(
                [sys.executable, "cmd/cage.py", "bundle", "verify", str(bundle)],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
