from __future__ import annotations

import unittest

from pathlib import Path

from core.modules.powershell_engine import powershell_engine_steps


class PowerShellEngineModuleTests(unittest.TestCase):
    def test_cfw_owned_windows_compatibility_is_not_reconstructed(self):
        source = Path(__file__).resolve().parents[1].joinpath(
            "core/modules/powershell_engine.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("get_bootstrap_profile", source)
        self.assertNotIn("windows_powershell51_steps", source)
        self.assertNotIn("install-dpx-helper.sh", source)
        self.assertNotIn("install-native-mscoree.sh", source)
        self.assertNotIn("install-powershell51.sh", source)

    def test_powershell_core_provider_is_explicitly_experimental_and_strict(self):
        steps = powershell_engine_steps()
        self.assertEqual(len(steps), 1)
        step = steps[0]
        script = "\n".join(step.commands)

        self.assertEqual(step.description, "Probe experimental PowerShell 7 engine")
        self.assertTrue(step.metadata["experimental"])
        self.assertIn("CAGE_MODULE_CACHE_DIR", script)
        self.assertIn("PowerShell-7.4.11-win-x64.zip", script)
        self.assertIn("558c4115cc6b96cc6a67d74bee40012cf8d38767537f8d2857dc3fa30a63cc63", script)
        self.assertIn("zipfile.ZipFile", script)
        self.assertIn("Program Files/PowerShell/7", script)
        self.assertIn("pwsh.exe", script)
        self.assertIn("engine-version=", script)
        self.assertIn('expected_version="7.4.11"', script)
        self.assertIn('chmod +x "$pwsh_exe"', script)
        self.assertNotIn("msiexec", script)
        self.assertNotIn("winetricks --unattended powershell_core", script)


if __name__ == "__main__":
    unittest.main()
