"""Contract tests for the public CFW-backed Chocolatey recipes."""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "recipes"
DOCS = ROOT / "docs"


class PublicChocolateyRecipeTests(unittest.TestCase):
    def _recipe(self, name: str) -> dict:
        with (RECIPES / name).open(encoding="utf-8") as stream:
            return yaml.safe_load(stream)

    def test_public_7zip_recipe_is_pinned_to_cfw_wine_11(self):
        recipe = self._recipe("7zip.cage.yaml")

        self.assertEqual(recipe["name"], "7zip")
        self.assertEqual(
            recipe["runtime"],
            {"provider": "wine", "version": "11.0", "network": "none", "wineGraphics": "xwayland"},
        )
        self.assertNotIn("compatibility", recipe)
        self.assertNotIn("runner", recipe["runtime"])
        self.assertEqual(recipe["modules"][0]["type"], "chocolatey")
        self.assertEqual(recipe["modules"][0]["install"]["packages"], ["7zip.install"])
        self.assertEqual(recipe["launch"]["entrypoint"], "C:/Program Files/7-Zip/7zFM.exe")

    def test_public_notepadplusplus_recipe_is_pinned_to_cfw_wine_11(self):
        recipe = self._recipe("notepadplusplus.cage.yaml")

        self.assertEqual(recipe["runtime"], {"provider": "wine", "version": "11.0", "network": "none", "wineGraphics": "xwayland"})
        self.assertNotIn("compatibility", recipe)
        self.assertNotIn("runner", recipe["runtime"])

    def test_legacy_pwschoco_recipe_is_not_public(self):
        self.assertFalse((RECIPES / "pwschoco.cage.yaml").exists())

    def test_public_package_workflow_emits_actionable_failure_annotations(self):
        workflow = (ROOT / ".github/workflows/chocolatey-public-package-proof.yml").read_text(encoding="utf-8")

        self.assertIn("title=7zip public package proof failed", workflow)
        self.assertIn("title=Notepad++ public package proof failed", workflow)
        self.assertIn("chocolatey-package-evidence.json", workflow)
        self.assertIn("chocolatey-diagnostic.json", workflow)
        self.assertIn("chocolatey-feature-policy.json", workflow)
        self.assertIn("chocolatey-smoke.json", workflow)

    def test_public_package_workflow_excludes_wine_prefix_from_direct_artifact_globs(self):
        workflow = (ROOT / ".github/workflows/chocolatey-public-package-proof.yml").read_text(encoding="utf-8")

        for package in ("7zip", "notepadplusplus"):
            self.assertIn(f"!dist-{package}/**/prefix/**", workflow)
        self.assertIn("evidence/7zip-bundle.tar.gz", workflow)
        self.assertIn("evidence/notepadplusplus-bundle.tar.gz", workflow)

    def test_public_package_workflow_is_credentialless_and_truthfully_named(self):
        workflow = (ROOT / ".github/workflows/chocolatey-public-package-proof.yml").read_text(encoding="utf-8")

        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("docker/login-action", workflow)
        self.assertNotIn("secrets.GITHUB_TOKEN", workflow)
        self.assertIn("Public Chocolatey Package Install and Launch-Plan Evidence", workflow)
        self.assertIn("launch-plan-evidence.json", workflow)
        self.assertNotIn("launch-evidence.json", workflow)

    def test_public_package_workflow_covers_all_proof_affecting_sources(self):
        workflow = (ROOT / ".github/workflows/chocolatey-public-package-proof.yml").read_text(encoding="utf-8")

        for path in (
            "core/manifest/**", "core/build_step.py", "core/chocolatey/**",
            "core/modules/**", "compat/**",
        ):
            with self.subTest(path=path):
                self.assertIn(f"- '{path}'", workflow)

    def test_chocolatey_recipe_docs_state_exact_cfw_release_and_wine_version(self):
        expected = "CFW v1.0.3"
        for path in (DOCS / "README.md", DOCS / "notepadplusplus-chocolatey.md"):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn(expected, text)
                self.assertIn("Wine 11", text)
                self.assertIn("must not declare `runtime.runner` or a Cage `compatibility` block", text)


if __name__ == "__main__":
    unittest.main()
