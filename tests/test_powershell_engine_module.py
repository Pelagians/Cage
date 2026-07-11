from __future__ import annotations

import unittest

from core.modules.powershell_engine import (
    WINDOWS_POWERSHELL_PROVIDER,
    powershell_engine_steps,
    windows_powershell51_steps,
)


class PowerShellEngineModuleTests(unittest.TestCase):
    def test_windows_powershell51_provider_uses_packaged_verified_installer(self):
        steps = windows_powershell51_steps()
        self.assertEqual(len(steps), 1)
        step = steps[0]
        script = "\n".join(step.commands)

        self.assertEqual(WINDOWS_POWERSHELL_PROVIDER, "windows-powershell-5.1-cfw")
        self.assertEqual(step.description, "Install Windows PowerShell 5.1 backend")
        self.assertEqual(step.kind, "wine-run")
        self.assertEqual(step.metadata["engine"], WINDOWS_POWERSHELL_PROVIDER)
        self.assertRegex(step.metadata["scriptSha256"], r"^[0-9a-f]{64}$")
        self.assertIn("Win7AndW2K8R2-KB3191566-x64.zip", script)
        self.assertIn("f383c34aa65332662a17d95409a2ddedadceda74427e35d05024cd0a6a2fa647", script)
        self.assertIn("ps51.exe", script)
        self.assertIn("wmf-cab-extract.log", script)
        self.assertIn("engine-version=", script)
        self.assertIn("fileSentinel", script)
        self.assertIn("stdoutMarker", script)

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
        self.assertIn("expected_version=\"7.4.11\"", script)
        self.assertIn('chmod +x "$pwsh_exe"', script)
        self.assertNotIn("msiexec", script)
        self.assertNotIn("winetricks --unattended powershell_core", script)


if __name__ == "__main__":
    unittest.main()
