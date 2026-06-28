"""Tests for application-first WinForge recipes and strict YAML loading."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from artifact.bundle import create_bundle
from artifact.inspection import verify_bundle
from core.manifest import ManifestError, load_manifest


APPLICATION_YAML = """
schemaVersion: winforge.app/v0
name: notepad-plus-plus
version: "8.6.0"
runtime:
  provider: wine
  version: "9.0"
sources:
  - name: installer
    url: https://example.invalid/npp.exe
    sha256: unverified-test-fixture
dependencies:
  - kind: winetricks
    verbs:
      - corefonts
      - vcrun2022
install:
  - kind: exe
    source: file://sources/npp.exe
    args:
      - /S
filesystem:
  - source: config.xml
    target: C:/Program Files/Notepad++/config.xml
config:
  wine:
    arch: win64
registry:
  - path: HKCU/Software/WinForge/Test
    values:
      InstalledBy: WinForge
launch:
  entrypoint: C:/Program Files/Notepad++/notepad++.exe
  args:
    - --multiInst
  env:
    APP_ENV: test
  workingDirectory: C:/Program Files/Notepad++
state:
  persistence: persistent
exports:
  - name: documents
    path: C:/users/winforge/Documents
provenance:
  sources: []
"""


class ApplicationRecipeYamlTests(unittest.TestCase):

    def test_load_manifest_accepts_application_yaml_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notepad-plus-plus.winforge.yaml"
            path.write_text(APPLICATION_YAML, encoding="utf-8")
            manifest = load_manifest(path)

        self.assertEqual(manifest.schema_version, "winforge.app/v0")
        self.assertEqual(manifest.name, "notepad-plus-plus")
        self.assertEqual(manifest.runtime.provider, "wine")
        self.assertEqual(manifest.runtime.version, "9.0")
        self.assertEqual(manifest.sources[0]["name"], "installer")
        self.assertEqual(manifest.config["wine"]["arch"], "win64")
        self.assertEqual(manifest.registry[0]["values"]["InstalledBy"], "WinForge")
        self.assertEqual(manifest.state["persistence"], "persistent")
        self.assertEqual(manifest.exports[0]["name"], "documents")
        self.assertEqual(manifest.launch.entrypoint, "C:/Program Files/Notepad++/notepad++.exe")

    def test_yaml_recipe_can_build_and_verify_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp) / "notepad-plus-plus.winforge.yaml"
            recipe.write_text(APPLICATION_YAML, encoding="utf-8")
            manifest = load_manifest(recipe)
            bundle = create_bundle(manifest, Path(tmp) / "dist", dry_run=True)
            result = verify_bundle(bundle)

        self.assertTrue(result["valid"], result["errors"])

    def test_unknown_root_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.winforge.yaml"
            path.write_text(APPLICATION_YAML + "surprise: nope\n", encoding="utf-8")
            with self.assertRaises(ManifestError) as cm:
                load_manifest(path)

        self.assertIn("unknown manifest field", str(cm.exception))

    def test_duplicate_yaml_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.winforge.yaml"
            path.write_text("""
schemaVersion: winforge.app/v0
name: first
name: second
version: "1.0.0"
runtime:
  provider: wine
  version: "9.0"
launch:
  entrypoint: C:/App/App.exe
""", encoding="utf-8")
            with self.assertRaises(ManifestError) as cm:
                load_manifest(path)

        self.assertIn("duplicate YAML key", str(cm.exception))

    def test_yaml_anchors_aliases_and_merge_keys_are_rejected(self):
        cases = {
            "anchor": """
schemaVersion: winforge.app/v0
name: anchored
version: "1.0.0"
runtime: &runtime
  provider: wine
  version: "9.0"
launch:
  entrypoint: C:/App/App.exe
""",
            "alias": """
schemaVersion: winforge.app/v0
name: alias
version: "1.0.0"
runtime: *runtime
launch:
  entrypoint: C:/App/App.exe
""",
            "merge": """
schemaVersion: winforge.app/v0
name: merge
version: "1.0.0"
runtime:
  <<: something
  provider: wine
  version: "9.0"
launch:
  entrypoint: C:/App/App.exe
""",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in cases.items():
                with self.subTest(name=name):
                    path = Path(tmp) / f"{name}.winforge.yaml"
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ManifestError) as cm:
                        load_manifest(path)
                    self.assertIn("YAML anchors, aliases, and merge keys are not supported", str(cm.exception))

    def test_json_manifest_remains_supported_for_cli_generated_or_normalized_inputs(self):
        data = {
            "schemaVersion": "winforge.dev/v0",
            "name": "json-app",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "9.0"},
            "dependencies": [],
            "install": [],
            "filesystem": [],
            "launch": {"entrypoint": "C:/App/App.exe"},
            "provenance": {"sources": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "generated.winforge.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            manifest = load_manifest(path)

        self.assertEqual(manifest.schema_version, "winforge.dev/v0")
        self.assertEqual(manifest.name, "json-app")


if __name__ == "__main__":
    unittest.main()
