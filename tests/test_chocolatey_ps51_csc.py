from __future__ import annotations

import unittest
from pathlib import Path

from core.chocolatey.assets import asset_sha256, load_asset
from core.chocolatey.assets.assembly_inventory import read_assembly_identity
from core.modules.powershell_engine import windows_powershell51_steps


ROOT = Path(__file__).resolve().parents[1]


class PowerShell51AssemblyInventoryContractTests(unittest.TestCase):
    def test_assembly_inventory_uses_hash_pinned_native_python(self):
        template = load_asset("install-powershell51.sh")
        helper_sha256 = asset_sha256("assembly_inventory.py")
        engine_step = windows_powershell51_steps()[1]
        rendered = "\n".join(engine_step.commands)

        self.assertRegex(helper_sha256, r"^[0-9a-f]{64}$")
        self.assertIn("{{ASSEMBLY_INVENTORY_PY_BASE64}}", template)
        self.assertIn("{{ASSEMBLY_INVENTORY_PY_SHA256}}", template)
        self.assertNotIn("{{ASSEMBLY_INVENTORY_PY_BASE64}}", rendered)
        self.assertNotIn("{{ASSEMBLY_INVENTORY_PY_SHA256}}", rendered)
        self.assertIn('python3 "$assembly_script" "$payload_root" "$assembly_map"', rendered)
        self.assertIn(helper_sha256, rendered)
        self.assertNotIn("csc.exe", template)
        self.assertNotIn('wine "$assembly_exe"', template)
        self.assertEqual(engine_step.metadata["assemblyInventorySha256"], helper_sha256)

    def test_metadata_reader_parses_a_real_managed_pe_fixture(self):
        fixture = ROOT / "core/chocolatey/assets/assembly-inventory.exe"
        identity = read_assembly_identity(fixture)

        self.assertEqual(identity.name, "assembly-inventory")
        self.assertEqual(identity.version, "0.0.0.0")
        self.assertEqual(identity.public_key_token, "")


if __name__ == "__main__":
    unittest.main()
