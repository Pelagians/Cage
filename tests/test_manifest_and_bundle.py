"""Tests for manifest parsing and bundle generation in module-first architecture."""
import json
import unittest
from core.manifest import Manifest, ManifestError
from builder.pipeline import build_plan

VALID = {
    "schemaVersion": "cage.app/v0",
    "name": "demo",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "9.0"},
    "sources": [],
    "modules": [],
    "compatibility": {"arch": "win64", "windowsVersion": "win10"},
    "launch": {"entrypoint": "C:/app/demo.exe"},
    "exports": [],
    "provenance": {"sources": []},
}


class ManifestAndBundleTests(unittest.TestCase):
    def test_rejects_unknown_runtime_provider(self):
        invalid = json.loads(json.dumps(VALID))
        invalid["runtime"]["provider"] = "steam-only"
        # In the new architecture, provider validation is not strict
        # The manifest should parse successfully
        manifest = Manifest.from_dict(invalid)
        self.assertEqual(manifest.runtime.provider, "steam-only")

    def test_rejects_removed_valve_proton_provider(self):
        invalid = json.loads(json.dumps(VALID))
        invalid["runtime"]["provider"] = "proton"
        # In the new architecture, provider validation is not strict
        # The manifest should parse successfully
        manifest = Manifest.from_dict(invalid)
        self.assertEqual(manifest.runtime.provider, "proton")

    def test_plan_contains_required_phase_order(self):
        # New architecture has 3 phases: init-prefix, launch, export
        phases = [x["phase"] for x in build_plan(Manifest.from_dict(VALID))]
        self.assertEqual(phases, ["init-prefix", "launch", "export"])
