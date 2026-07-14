from __future__ import annotations

import unittest

from core.modules.powershell_engine import (
    CFW_DPX_PROVIDER,
    WINDOWS_POWERSHELL_PROVIDER,
    powershell_engine_steps,
    windows_powershell51_steps,
)


class PowerShellEngineModuleTests(unittest.TestCase):
    def test_windows_powershell51_provider_uses_explicit_dpx_prerequisite(self):
        steps = windows_powershell51_steps()
        self.assertEqual(len(steps), 2)
        helper, engine = steps
        helper_script = "\n".join(helper.commands)
        engine_script = "\n".join(engine.commands)

        self.assertEqual(WINDOWS_POWERSHELL_PROVIDER, "windows-powershell-5.1-cfw")
        self.assertEqual(CFW_DPX_PROVIDER, "cfw-dpx-helper-from-c-drive")
        self.assertEqual(helper.description, "Install CFW native DPX extraction helper")
        self.assertEqual(helper.kind, "wine-run")
        self.assertEqual(helper.metadata["provider"], CFW_DPX_PROVIDER)
        self.assertRegex(helper.metadata["scriptSha256"], r"^[0-9a-f]{64}$")
        self.assertIn("c_drive.7z", helper_script)
        self.assertIn("retained-cfw-component", helper_script)
        self.assertIn("cfw-c-drive-inventory.log", helper_script)
        self.assertIn("system32/expnd", helper_script)
        self.assertIn("dpx.dll", helper_script)
        self.assertIn("msdelta.dll", helper_script)
        self.assertNotIn("powershell2.7z", helper_script)

        self.assertEqual(engine.description, "Install Windows PowerShell 5.1 backend")
        self.assertEqual(engine.kind, "wine-run")
        self.assertEqual(engine.metadata["engine"], WINDOWS_POWERSHELL_PROVIDER)
        self.assertEqual(engine.metadata["requires"], CFW_DPX_PROVIDER)
        self.assertRegex(engine.metadata["scriptSha256"], r"^[0-9a-f]{64}$")
        self.assertIn("Win7AndW2K8R2-KB3191566-x64.zip", engine_script)
        self.assertIn("f383c34aa65332662a17d95409a2ddedadceda74427e35d05024cd0a6a2fa647", engine_script)
        self.assertIn("ps51.exe", engine_script)
        self.assertIn("wmf-dpx-extract.log", engine_script)
        self.assertIn("sourceName", engine_script)
        self.assertIn("skipped-files.log", engine_script)
        self.assertIn("engine-version=", engine_script)
        self.assertIn("fileSentinel", engine_script)
        self.assertIn("stdoutMarker", engine_script)

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
