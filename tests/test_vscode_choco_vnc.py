from __future__ import annotations

import unittest
from pathlib import Path

from core.manifest import load_manifest


class VSCodeChocoVNCTests(unittest.TestCase):
    def test_vscode_choco_vnc_loads_and_has_expected_structure(self):
        repo = Path(__file__).resolve().parents[1]
        recipe = repo / "examples" / "vscode-choco-vnc.cage.yaml"
        manifest = load_manifest(recipe)

        self.assertEqual(manifest.name, "vscode-choco-vnc")
        self.assertEqual([m.type for m in manifest.modules], ["chocolatey"])
        self.assertEqual(manifest.runtime.provider, "wine")
        self.assertEqual(manifest.runtime.version, "11.0")
        self.assertEqual(manifest.runtime.network, "bridge")
        self.assertEqual(manifest.launch.entrypoint, "/opt/wine/bin/winevnc.sh")
        self.assertIn("C:/Program Files/Microsoft VS Code/Code.exe", manifest.launch.args)
        self.assertEqual(manifest.launch.env.get("VNC_GEOMETRY"), "1920x1080")
        
        # Verify chocolatey module structure
        choco_module = manifest.modules[0]
        self.assertEqual(choco_module.type, "chocolatey")
        self.assertIn("visualstudio.code", choco_module.install["packages"])
