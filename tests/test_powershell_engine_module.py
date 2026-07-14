from __future__ import annotations

import unittest

from core.modules.powershell_engine import (
    CFW_DPX_PROVIDER,
    CFW_MSCOREE_PROVIDER,
    WINDOWS_POWERSHELL_PROVIDER,
    powershell_engine_steps,
    windows_powershell51_steps,
)


class PowerShellEngineModuleTests(unittest.TestCase):
    def test_windows_powershell51_provider_uses_explicit_native_prerequisites(self):
        steps = windows_powershell51_steps()
        self.assertEqual(len(steps), 3)
        helper, loader, engine = steps
        helper_script = "\n".join(helper.commands)
        loader_script = "\n".join(loader.commands)
        engine_script = "\n".join(engine.commands)

        self.assertEqual(WINDOWS_POWERSHELL_PROVIDER, "windows-powershell-5.1-cfw")
        self.assertEqual(CFW_DPX_PROVIDER, "cfw-dpx-helper-aik-winpe")
        self.assertEqual(CFW_MSCOREE_PROVIDER, "cfw-native-mscoree-kb958488")

        self.assertEqual(helper.description, "Install CFW native DPX extraction helper")
        self.assertEqual(helper.kind, "wine-run")
        self.assertEqual(helper.metadata["provider"], CFW_DPX_PROVIDER)
        self.assertRegex(helper.metadata["scriptSha256"], r"^[0-9a-f]{64}$")
        self.assertIn("KB3AIK_EN.iso", helper_script)
        self.assertIn('range_start="640526336"', helper_script)
        self.assertIn('range_end="1086964920"', helper_script)
        self.assertIn("b8db22bef35f091b6b63d223118c55f833856be0d535465ce5a06a51ff38fa27", helper_script)
        self.assertIn("fdfd889f5131898d9a3e68e39c24d8d6ad1f53765522f0280899e54620be47ff", helper_script)
        self.assertIn("system32/expnd", helper_script)
        self.assertIn("cabinet.dll", helper_script)
        self.assertIn("dpx.dll", helper_script)
        self.assertIn("msdelta.dll", helper_script)
        self.assertNotIn("powershell2.7z", helper_script)
        self.assertNotIn("c_drive.7z", helper_script)

        self.assertEqual(loader.description, "Install native .NET MSCoree loader")
        self.assertEqual(loader.kind, "wine-run")
        self.assertEqual(loader.metadata["provider"], CFW_MSCOREE_PROVIDER)
        self.assertRegex(loader.metadata["scriptSha256"], r"^[0-9a-f]{64}$")
        self.assertIn("windows6.1-kb958488-v6001-x64", loader_script)
        self.assertIn("a5f4243ce8b07c9222284fd8ff6f7e742d934c57c89de9cab5d88c74402264e3", loader_script)
        self.assertIn("81d3951c736cccb9578eed19ca9f1d7f68fc17dde1d87eadea72767adbe81734", loader_script)
        self.assertIn("758e5ba89665c574456a2a826ef5a7dc2487c8379893010eb57bc40127ac918f", loader_script)
        self.assertIn("46e9715f3cd09f32fbeaa5379991e9e7daccbd2407c2d061fda3a04f05108133", loader_script)
        self.assertIn("C:/Windows/System32/mscoree.dll", loader_script)
        self.assertIn("C:/Windows/SysWOW64/mscoree.dll", loader_script)
        self.assertIn("/v mscoree /d native /f", loader_script)
        self.assertIn("native-mscoree.json", loader_script)

        self.assertEqual(engine.description, "Install Windows PowerShell 5.1 backend")
        self.assertEqual(engine.kind, "wine-run")
        self.assertEqual(engine.metadata["engine"], WINDOWS_POWERSHELL_PROVIDER)
        self.assertEqual(engine.metadata["requires"], [CFW_DPX_PROVIDER, CFW_MSCOREE_PROVIDER])
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
