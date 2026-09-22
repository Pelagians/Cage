"""Tests for Phase 5A runner catalog aliases and resolved runtime metadata."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from artifact.bundle import create_bundle
from core.manifest import Manifest
from runtime.launcher import build_run_plan

LATEST_WINE = {
    "schemaVersion": "cage.app/v0",
    "name": "latest-wine-app",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "latest"},
    "launch": {"entrypoint": "C:/App/App.exe"},
    "provenance": {"sources": []},
}


class Phase5ARunnerCatalogTests(unittest.TestCase):
    def test_bundle_records_requested_and_resolved_runtime_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(
                Manifest.from_dict(LATEST_WINE), Path(tmp), dry_run=True
            )
            runtime = json.loads(
                (bundle / "runtime/runtime.json").read_text(encoding="utf-8")
            )
            graph = json.loads(
                (bundle / "metadata/graph.json").read_text(encoding="utf-8")
            )
            provenance = json.loads(
                (bundle / "metadata/provenance.json").read_text(encoding="utf-8")
            )

        self.assertEqual(runtime["provider"], "wine")
        self.assertEqual(runtime["requestedVersion"], "latest")
        self.assertEqual(runtime["resolvedVersion"], "11.0")
        self.assertEqual(runtime["version"], "11.0")
        self.assertEqual(runtime["runner"], "winehq-stable")
        self.assertEqual(runtime["packageVersion"], "11.0.0.0~trixie-1")
        self.assertEqual(runtime["ociImage"], "ghcr.io/pelagians/cage-wine:11.0")
        self.assertEqual(graph["runnerRuntime"]["requestedVersion"], "latest")
        self.assertEqual(graph["runnerRuntime"]["resolvedVersion"], "11.0")
        self.assertEqual(
            graph["runnerRuntime"]["image"], "ghcr.io/pelagians/cage-wine:11.0"
        )
        self.assertEqual(provenance["runtime"]["resolvedVersion"], "11.0")

    def test_run_plan_for_latest_uses_resolved_runtime_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(
                Manifest.from_dict(LATEST_WINE), Path(tmp), dry_run=True
            )
            plan = build_run_plan(
                bundle, graphics="headless", engine="podman", allow_non_runnable=True
            )

        self.assertEqual(plan["runtime"]["provider"], "wine")
        self.assertEqual(plan["runtime"]["requestedVersion"], "latest")
        self.assertEqual(plan["runtime"]["resolvedVersion"], "11.0")
        self.assertEqual(plan["runtime"]["version"], "11.0")
        self.assertEqual(plan["runtime"]["image"], "ghcr.io/pelagians/cage-wine:11.0")

    def test_wine_channels_share_a_pinned_package_build(self):
        root = Path(__file__).resolve().parents[1]
        wine = (root / "container/runtimes/wine/Dockerfile").read_text(encoding="utf-8")
        from runtime.catalog import resolve_catalog_version
        staging = resolve_catalog_version("staging", "latest")
        self.assertIsNotNone(staging)
        assert staging is not None
        self.assertEqual(staging.dockerfile, "container/runtimes/wine/Dockerfile")
        self.assertEqual(staging.build_arg_line(), "WINE_PACKAGE_VERSION=11.10~trixie-1")
        self.assertIn("ARG WINE_PACKAGE_VERSION=11.0.0.0~trixie-1", wine)
        self.assertIn("ARG WINE_CHANNEL=stable", wine)
        self.assertIn("stable|staging", wine)
        self.assertIn("winehq-${WINE_CHANNEL}=${WINE_PACKAGE_VERSION}", wine)
        self.assertIn("wine-${WINE_CHANNEL}-i386:i386=${WINE_PACKAGE_VERSION}", wine)
        self.assertIn("--build-arg WINE_CHANNEL=staging", (root / "container/build.sh").read_text())
        self.assertIn('"WINE_CHANNEL=staging"', (root / "container/manager.py").read_text())


if __name__ == "__main__":
    unittest.main()
