"""Tests for manifest parsing and bundle generation in module-first architecture."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from builder.pipeline import build_plan
from core.manifest import Manifest, ManifestError, load_manifest


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

        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(invalid)

        self.assertIn("unsupported runtime provider", str(ctx.exception))

    def test_rejects_removed_valve_proton_provider(self):
        invalid = json.loads(json.dumps(VALID))
        invalid["runtime"]["provider"] = "proton"

        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(invalid)

        self.assertIn("unsupported runtime provider", str(ctx.exception))

    def test_rejects_unknown_runtime_version(self):
        invalid = json.loads(json.dumps(VALID))
        invalid["runtime"]["version"] = "wine-does-not-exist"

        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(invalid)

        self.assertIn("unsupported runtime version", str(ctx.exception))

    def test_runtime_image_ref_overrides_after_catalog_validation_only(self):
        valid = json.loads(json.dumps(VALID))
        valid["runtime"]["imageRef"] = "registry.example/cage-wine:custom"

        manifest = Manifest.from_dict(valid)

        self.assertEqual(manifest.runtime.image, "registry.example/cage-wine:custom")

        invalid = json.loads(json.dumps(valid))
        invalid["runtime"]["version"] = "wine-does-not-exist"
        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(invalid)

        self.assertIn("unsupported runtime version", str(ctx.exception))

    def test_rejects_legacy_root_fields_not_in_v0_contract(self):
        for field, value in {
            "dependencies": [],
            "install": [],
            "registry": [],
            "state": {},
        }.items():
            with self.subTest(field=field):
                invalid = json.loads(json.dumps(VALID))
                invalid[field] = value

                with self.assertRaises(ManifestError) as ctx:
                    Manifest.from_dict(invalid)

                self.assertIn(field, str(ctx.exception))

    def test_rejects_unknown_source_type_and_policy(self):
        for field, value in {"type": "http", "policy": "required"}.items():
            with self.subTest(field=field):
                invalid = json.loads(json.dumps(VALID))
                invalid["sources"] = [{
                    "id": "installer",
                    "type": "installer",
                    "policy": "redistributable",
                    "url": "https://example.invalid/app.exe",
                }]
                invalid["sources"][0][field] = value

                with self.assertRaises(ManifestError) as ctx:
                    Manifest.from_dict(invalid)

                self.assertIn(f"sources[0].{field}", str(ctx.exception))

    def test_normalizes_compatibility_policy_at_parse_time(self):
        manifest = Manifest.from_dict(VALID)

        self.assertEqual(manifest.compatibility["schemaVersion"], "cage.compatibility-policy/v0")
        self.assertEqual(manifest.compatibility["arch"], "win64")

    def test_rejects_invalid_compatibility_policy_at_parse_time(self):
        invalid = json.loads(json.dumps(VALID))
        invalid["compatibility"]["arch"] = "arm64"

        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(invalid)

        self.assertIn("compatibility.arch", str(ctx.exception))


    def test_launch_is_optional_for_planning_bundles(self):
        from artifact.bundle import create_bundle
        from artifact.inspection import verify_bundle
        data = json.loads(json.dumps(VALID))
        data.pop("launch")

        manifest = Manifest.from_dict(data)
        self.assertIsNone(manifest.launch)

        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=True)
            launch_payload = json.loads((bundle / "launch/entrypoint.json").read_text(encoding="utf-8"))
            status = json.loads((bundle / "metadata/status.json").read_text(encoding="utf-8"))
            verification = verify_bundle(bundle)

        self.assertFalse(launch_payload["hasDefaultLaunch"])
        self.assertFalse(status["hasDefaultLaunch"])
        self.assertFalse(verification["runnable"])
        self.assertFalse(verification["status"]["hasDefaultLaunch"])

    def test_build_network_is_separate_from_runtime_network(self):
        data = json.loads(json.dumps(VALID))
        data["build"] = {"network": "host"}
        data["runtime"]["network"] = "none"

        manifest = Manifest.from_dict(data)

        self.assertEqual(manifest.build.network, "host")
        self.assertEqual(manifest.runtime.network, "none")
        self.assertEqual(manifest.to_dict()["build"], {"network": "host"})

    def test_runtime_image_override_is_preserved_without_catalog_lookup_for_image(self):
        data = json.loads(json.dumps(VALID))
        data["runtime"]["image"] = "registry.example.invalid/cage-wine-custom:dev"

        manifest = Manifest.from_dict(data)

        self.assertEqual(manifest.runtime.image, "registry.example.invalid/cage-wine-custom:dev")
        self.assertEqual(manifest.to_dict()["runtime"]["image"], "registry.example.invalid/cage-wine-custom:dev")

    def test_launch_working_directory_is_preserved(self):
        data = json.loads(json.dumps(VALID))
        data["launch"]["workingDirectory"] = "C:/app"

        manifest = Manifest.from_dict(data)

        self.assertEqual(manifest.launch.working_directory, "C:/app")
        self.assertEqual(manifest.to_dict()["launch"]["workingDirectory"], "C:/app")

    def test_load_manifest_rejects_strict_yaml_hazards(self):
        cases = {
            "duplicate": "schemaVersion: cage.app/v0\nschemaVersion: cage.app/v0\n",
            "anchor": "schemaVersion: &schema cage.app/v0\n",
            "alias": "schemaVersion: *schema\n",
            "merge": "<<: *defaults\n",
            "tab": "schemaVersion:\t cage.app/v0\n",
            "odd_indent": "schemaVersion: cage.app/v0\n name: demo\n",
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name, text in cases.items():
                with self.subTest(name=name):
                    manifest_path = tmp_path / f"{name}.cage.yaml"
                    manifest_path.write_text(text, encoding="utf-8")

                    with self.assertRaises(ManifestError):
                        load_manifest(manifest_path)

    def test_plan_contains_required_phase_order(self):
        phases = [x["phase"] for x in build_plan(Manifest.from_dict(VALID))]
        self.assertEqual(phases, ["init-prefix", "launch", "export"])

    def test_build_plan_serializes_step_kind_and_safety(self):
        data = json.loads(json.dumps(VALID))
        data["modules"] = [{"type": "script", "command": "echo unsafe"}]

        module_step = build_plan(Manifest.from_dict(data))[1]

        self.assertEqual(module_step["kind"], "raw-shell")
        self.assertTrue(module_step["unsafe"])
        self.assertEqual(module_step["moduleType"], "script")


if __name__ == "__main__":
    unittest.main()
