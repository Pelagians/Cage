"""Tests for Cage execution graph generation."""
from __future__ import annotations
from contextlib import redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from artifact.bundle import create_bundle
from artifact.graph import build_execution_graph
from cage.cli import cmd_inspect, cmd_plan
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
        "args": ["--safe-mode"],
        "env": {"WINEDLLOVERRIDES": "mscoree,mshtml=disabled"},
        "workingDirectory": "C:/Program Files/App",
    },
    "provenance": {"sources": []},
}


class ExecutionGraphTests(unittest.TestCase):

    def test_cfw_graph_and_runtime_metadata_use_exact_producer_image(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "cfw-graph",
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
                    "wineImage": image,
                    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
                },
            }}],
        }
        manifest = Manifest.from_dict(data)
        graph = build_execution_graph(manifest)
        self.assertEqual(graph["builderRuntime"]["image"], image)
        self.assertEqual(graph["runnerRuntime"]["image"], image)
        self.assertEqual(graph["builderRuntime"]["ociImage"], image)
        self.assertEqual(graph["builderRuntime"]["environment"], {"WINEDLLOVERRIDES": ""})
        self.assertEqual(graph["runnerRuntime"]["environment"], {"WINEDLLOVERRIDES": ""})
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=True)
            runtime = json.loads((bundle / "runtime/runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime["ociImage"], image)
        self.assertEqual(runtime["environment"], {"WINEDLLOVERRIDES": ""})

    def test_cfw_inspect_and_plan_use_exact_producer_image(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "cfw-cli",
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
                    "wineImage": image,
                    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
                },
            }}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            inspect_output = io.StringIO()
            with redirect_stdout(inspect_output):
                self.assertEqual(cmd_inspect(SimpleNamespace(manifest=str(path))), 0)
            plan_output = io.StringIO()
            with redirect_stdout(plan_output):
                self.assertEqual(cmd_plan(SimpleNamespace(manifest=str(path))), 0)

        self.assertEqual(json.loads(inspect_output.getvalue())["resolvedRuntime"]["ociImage"], image)
        self.assertEqual(json.loads(plan_output.getvalue())["ociImage"], image)

    def test_graph_records_resolved_runtime_launch_graphics_and_compatibility(self):
        graph = build_execution_graph(Manifest.from_dict(VALID))

        self.assertEqual(graph["schemaVersion"], "cage.execution-graph/v0")
        self.assertEqual(graph["application"], {"name": "sample", "version": "1.0.0"})
        self.assertEqual(graph["artifact"]["kind"], "cage.bundle")
        self.assertEqual(graph["builderRuntime"]["provider"], "wine")
        self.assertEqual(graph["builderRuntime"]["version"], "9.0")
        self.assertEqual(graph["builderRuntime"]["image"], "ghcr.io/pelagians/cage-wine:9.0")
        self.assertNotIn("network", graph["builderRuntime"])
        self.assertEqual(graph["runnerRuntime"]["network"], "none")
        self.assertEqual(
            {k: v for k, v in graph["runnerRuntime"].items() if k != "network"},
            graph["builderRuntime"],
        )
        self.assertEqual(graph["graphics"]["defaultMode"], "headless")
        self.assertEqual(graph["graphics"]["supportedModes"], ["headless", "vnc"])
        self.assertEqual(graph["launch"]["entrypoint"], "C:/Program Files/App/App.exe")
        self.assertEqual(graph["launch"]["args"], ["--safe-mode"])
        self.assertTrue(graph["compatibility"]["requiresExactRuntime"])

    def test_graph_has_deterministic_phase_nodes_and_edges(self):
        first = build_execution_graph(Manifest.from_dict(VALID))
        second = build_execution_graph(Manifest.from_dict(VALID))
        self.assertEqual(first, second)

        node_ids = [node["id"] for node in first["nodes"]]
        self.assertIn("runtime:wine:9.0", node_ids)
        self.assertIn("phase:init-prefix", node_ids)
        self.assertIn("phase:export", node_ids)
        self.assertIn("artifact:bundle", node_ids)

        edges = {(edge["from"], edge["to"], edge["type"]) for edge in first["edges"]}
        self.assertIn(("manifest:sample:1.0.0", "runtime:wine:9.0", "resolves"), edges)
        self.assertIn(("phase:launch", "phase:export", "precedes"), edges)
        self.assertIn(("phase:export", "artifact:bundle", "produces"), edges)

    def test_bundle_writes_metadata_graph_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(VALID), Path(tmp), dry_run=True)
            graph_path = bundle / "metadata" / "graph.json"
            self.assertTrue(graph_path.exists())
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            self.assertEqual(graph["schemaVersion"], "cage.execution-graph/v0")
            self.assertEqual(graph["builderRuntime"]["image"], "ghcr.io/pelagians/cage-wine:9.0")


if __name__ == "__main__":
    unittest.main()
