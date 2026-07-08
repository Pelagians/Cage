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
        self.assertIn("PowerShell capability", message)
        self.assertIn("chocolatey", message)
        self.assertIn("powershell-wrapper", message)

    def test_powershell_wrapper_uses_shared_engine_and_checksummed_assets(self):
        manifest = Manifest.from_dict(_base_manifest([
            {"type": "powershell-wrapper", "version": "7"},
        ]))
        steps = manifest.modules[0].build()
        descriptions = [step.description for step in steps]
        script = "\n".join("\n".join(step.commands) for step in steps)

        self.assertEqual(descriptions, [
            "Install PowerShell 7 engine",
            "Install PowerShell wrapper (v4.2.0)",
        ])
        self.assertIn("CAGE_MODULE_CACHE_DIR", script)
        self.assertIn("b1d594bd44abc01007b9dd2adea5248f09906fa8d4c6cea7f36a4279e2de91e0", script)
        self.assertIn("ca76d774273ffa37053545f8e4ad63c8914461828f1d1eef7a1915c9656fed4c", script)
        self.assertIn("f2ae629da40bbd60f66554dc87f3145bb6ca9b2adc6eda3be515438c8bee2e24", script)
        self.assertIn("actual_wrapper64_sha", script)
        self.assertIn("actual_wrapper32_sha", script)
        self.assertIn("actual_profile_sha", script)
        self.assertNotIn("winetricks --unattended powershell_core", script)
        self.assertNotIn('export WINEDLLOVERRIDES=""', script)


if __name__ == "__main__":
    unittest.main()
