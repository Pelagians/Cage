from __future__ import annotations

import unittest

from core.chocolatey.assets import asset_sha256, load_asset, load_asset_bytes
from core.modules.powershell_engine import windows_powershell51_steps


class PowerShell51PrecompiledHelperContractTests(unittest.TestCase):
    def test_assembly_inventory_uses_a_hash_pinned_precompiled_asset(self):
        template = load_asset("install-powershell51.sh")
        helper = load_asset_bytes("assembly-inventory.exe")
        helper_source = load_asset("assembly-inventory.cs")
        helper_sha256 = asset_sha256("assembly-inventory.exe")
        engine_step = windows_powershell51_steps()[1]
        rendered = "\n".join(engine_step.commands)

        self.assertTrue(helper.startswith(b"MZ"))
        self.assertRegex(helper_sha256, r"^[0-9a-f]{64}$")
        self.assertIn("AssemblyName.GetAssemblyName", helper_source)
        self.assertIn("{{ASSEMBLY_INVENTORY_EXE_BASE64}}", template)
        self.assertIn("{{ASSEMBLY_INVENTORY_EXE_SHA256}}", template)
        self.assertNotIn("csc.exe", template)
        self.assertNotIn("{{ASSEMBLY_INVENTORY_EXE_BASE64}}", rendered)
        self.assertNotIn("{{ASSEMBLY_INVENTORY_EXE_SHA256}}", rendered)
        self.assertIn("base64 -d", rendered)
        self.assertIn(helper_sha256, rendered)
        self.assertEqual(engine_step.metadata["assemblyInventorySha256"], helper_sha256)


if __name__ == "__main__":
    unittest.main()
