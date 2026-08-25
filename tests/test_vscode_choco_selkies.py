from __future__ import annotations

import unittest
from pathlib import Path

from core.manifest import load_manifest


class VSCodeChocoSelkiesTests(unittest.TestCase):
    def test_vscode_choco_selkies_loads_and_has_expected_structure(self):
        repo = Path(__file__).resolve().parents[1]
        manifest = load_manifest(repo / "examples" / "vscode-choco-selkies.cage.yaml")

        self.assertEqual(manifest.name, "vscode-choco-selkies")
        self.assertEqual([module.type for module in manifest.modules], ["chocolatey"])
        self.assertEqual(manifest.runtime.provider, "wine")
        self.assertEqual(manifest.runtime.version, "11.0")
        self.assertEqual(manifest.runtime.network, "bridge")
        self.assertEqual(manifest.runtime.wine_graphics, "xwayland")
        self.assertEqual(
            manifest.launch.entrypoint,
            "C:/Program Files/Microsoft VS Code/Code.exe",
        )
        self.assertIn("visualstudio.code", manifest.modules[0].install["packages"])
