from __future__ import annotations

import unittest

from core.manifest import Manifest, ManifestError, resolve_module_capabilities
from core.modules import ModuleError, PowerShellWrapperModule


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

    def test_powershell_wrapper_and_chocolatey_share_canonical_providers(self):
        manifest = Manifest.from_dict(_base_manifest([
            {"type": "powershell-wrapper", "version": "7"},
            {"type": "chocolatey", "install": {"packages": ["7zip"]}},
        ]))

        resolved = resolve_module_capabilities(manifest.modules)
        self.assertEqual(resolved["engine"]["provider"], "powershell-zip-7.4.11")
        self.assertEqual(resolved["winps-shim"]["provider"], "synchro-v4.2.0")
        self.assertEqual(resolved["package-manager"]["provider"], "chocolatey-2.6.0")
        self.assertEqual(resolved["compatibility-pack"]["provider"], "chocolatey-for-wine-v1")

    def test_powershell_wrapper_uses_shared_engine_loader_and_checksummed_assets(self):
        manifest = Manifest.from_dict(_base_manifest([
            {"type": "powershell-wrapper", "version": "7"},
        ]))
        steps = manifest.modules[0].build()
        descriptions = [step.description for step in steps]
        script = "\n".join("\n".join(step.commands) for step in steps)

        self.assertEqual(descriptions, [
            "Install canonical PowerShell 7 engine",
            "Install canonical Synchro PowerShell layer (v4.2.0)",
        ])
        self.assertIn("CAGE_MODULE_CACHE_DIR", script)
        self.assertIn("b1d594bd44abc01007b9dd2adea5248f09906fa8d4c6cea7f36a4279e2de91e0", script)
        self.assertIn("ca76d774273ffa37053545f8e4ad63c8914461828f1d1eef7a1915c9656fed4c", script)
        self.assertIn("f2ae629da40bbd60f66554dc87f3145bb6ca9b2adc6eda3be515438c8bee2e24", script)
        self.assertIn('profile_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"', script)
        self.assertIn('fragment_dir="$profile_root/profile.d"', script)
        self.assertIn("10-synchro.ps1", script)
        self.assertIn("upstream/synchro-v4.2.0", script)
        self.assertIn("profile_loader_b64", script)
        self.assertIn("synchro-x64-ok", script)
        self.assertIn("synchro-x86-ok", script)
        self.assertIn("exit 37", script)
        self.assertNotIn("winetricks --unattended powershell_core", script)
        self.assertNotIn('export WINEDLLOVERRIDES=""', script)

    def test_unpinned_wrapper_version_is_rejected(self):
        manifest = Manifest.from_dict(_base_manifest([
            {"type": "powershell-wrapper", "version": "7", "wrapperVersion": "v9.9.9"},
        ]))

        with self.assertRaises(ModuleError) as ctx:
            manifest.modules[0].build()

        self.assertIn("only the pinned, checksummed release v4.2.0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
