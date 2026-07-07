"""Tests for Cage bundle inspect/verify commands."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from artifact.bundle import create_bundle
from artifact.inspection import inspect_bundle, verify_bundle
from core.manifest import Manifest


VALID = {
    "schemaVersion": "cage.dev/v0",
    "name": "sample",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "9.0"},
    "dependencies": [{"kind": "winetricks", "verbs": ["corefonts"]}],
    "install": [{
        "kind": "portable",
        "source": "file://app.zip",
        "target": "C:/Program Files/App",
    }],
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
        self.assertEqual(summary["graph"]["nodes"], 11)
        self.assertEqual(summary["graph"]["edges"], 13)
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
