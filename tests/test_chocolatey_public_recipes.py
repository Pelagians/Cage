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
            {"provider": "wine", "version": "11.0", "network": "none"},
        )
        self.assertNotIn("compatibility", recipe)
        self.assertNotIn("runner", recipe["runtime"])
        self.assertEqual(recipe["modules"][0]["type"], "chocolatey")
        self.assertEqual(recipe["modules"][0]["install"]["packages"], ["7zip.install"])
        self.assertEqual(recipe["launch"]["entrypoint"], "C:/Program Files/7-Zip/7zFM.exe")

    def test_public_notepadplusplus_recipe_is_pinned_to_cfw_wine_11(self):
        recipe = self._recipe("notepadplusplus.cage.yaml")

        self.assertEqual(recipe["runtime"], {"provider": "wine", "version": "11.0", "network": "none"})
        self.assertNotIn("compatibility", recipe)
        self.assertNotIn("runner", recipe["runtime"])

    def test_legacy_pwschoco_recipe_is_not_public(self):
        self.assertFalse((RECIPES / "pwschoco.cage.yaml").exists())

    def test_chocolatey_recipe_docs_state_exact_cfw_release_and_wine_version(self):
        expected = "CFW v1.0.2"
        for path in (DOCS / "README.md", DOCS / "notepadplusplus-chocolatey.md"):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn(expected, text)
                self.assertIn("Wine 11", text)
                self.assertIn("must not declare `runtime.runner` or a Cage `compatibility` block", text)


if __name__ == "__main__":
    unittest.main()
