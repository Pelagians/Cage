from __future__ import annotations

import unittest

from core.manifest import Manifest, ManifestError
from core.modules import PowerShellWrapperModule


def _base_manifest(modules: list[dict]) -> dict:
    return {
        "schemaVersion": "cage.app/v0",
        "name": "test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "latest"},
        "modules": modules,
    }


class PowerShellWrapperModuleTests(unittest.TestCase):
    def test_powershell_wrapper_module_parses_under_new_name(self):
        manifest = Manifest.from_dict(_base_manifest([
            {"type": "powershell-wrapper", "version": "7"},
        ]))

        self.assertEqual([m.type for m in manifest.modules], ["powershell-wrapper"])
        self.assertIsInstance(manifest.modules[0], PowerShellWrapperModule)

    def test_legacy_powershell_module_name_is_rejected(self):
        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(_base_manifest([
                {"type": "powershell", "version": "7"},
            ]))

        self.assertIn("powershell-wrapper", str(ctx.exception))

    def test_powershell_wrapper_and_chocolatey_cannot_be_mixed_yet(self):
        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(_base_manifest([
                {"type": "powershell-wrapper", "version": "7"},
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ]))

        message = str(ctx.exception)
        self.assertIn("cannot be used together", message)
        self.assertIn("chocolatey", message)
        self.assertIn("powershell-wrapper", message)


if __name__ == "__main__":
    unittest.main()
