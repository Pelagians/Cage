from __future__ import annotations

import unittest

from core.manifest import Manifest, ManifestError
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

    def test_experimental_core_module_conflicts_with_verified_chocolatey_engine(self):
        with self.assertRaises(ManifestError) as ctx:
            Manifest.from_dict(_base_manifest([
                {"type": "powershell-wrapper", "version": "7"},
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ]))

        message = str(ctx.exception)
        self.assertIn("slot 'engine'", message)
        self.assertIn("powershell-zip-7.4.11", message)
        self.assertIn("windows-powershell-5.1-cfw", message)

    def test_standalone_module_is_only_a_strict_core_runtime_probe(self):
        manifest = Manifest.from_dict(_base_manifest([
            {"type": "powershell-wrapper", "version": "7"},
        ]))
        steps = manifest.modules[0].build()
        descriptions = [step.description for step in steps]
        script = "\n".join("\n".join(step.commands) for step in steps)

        self.assertEqual(descriptions, ["Probe experimental PowerShell 7 engine"])
        self.assertTrue(steps[0].metadata["experimental"])
        self.assertIn("CAGE_MODULE_CACHE_DIR", script)
        self.assertIn("PowerShell-7.4.11-win-x64.zip", script)
        self.assertIn("558c4115cc6b96cc6a67d74bee40012cf8d38767537f8d2857dc3fa30a63cc63", script)
        self.assertIn("engine-version=", script)
        self.assertNotIn("powershell64.exe", script)
        self.assertNotIn("10-synchro.ps1", script)

    def test_unpinned_wrapper_version_is_rejected(self):
        manifest = Manifest.from_dict(_base_manifest([
            {"type": "powershell-wrapper", "version": "7", "wrapperVersion": "v9.9.9"},
        ]))

        with self.assertRaises(ModuleError) as ctx:
            manifest.modules[0].build()

        self.assertIn("only the pinned, checksummed release v4.2.0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
