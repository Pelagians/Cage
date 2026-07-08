from __future__ import annotations

import unittest

from core.modules.powershell_engine import powershell_engine_steps


class PowerShellEngineModuleTests(unittest.TestCase):
    def test_powershell_engine_uses_pinned_zip_and_module_cache(self):
        steps = powershell_engine_steps()
        self.assertEqual(len(steps), 1)
        step = steps[0]
        script = "\n".join(step.commands)

        self.assertIn("Install PowerShell 7 engine", step.description)
        self.assertIn("CAGE_MODULE_CACHE_DIR", script)
        self.assertIn("PowerShell-7.4.11-win-x64.zip", script)
        self.assertIn("558c4115cc6b96cc6a67d74bee40012cf8d38767537f8d2857dc3fa30a63cc63", script)
        self.assertIn("zipfile.ZipFile", script)
        self.assertIn("Program Files/PowerShell/7", script)
        self.assertIn("pwsh.exe", script)
        self.assertIn("actual_pwsh_zip_sha", script)
        self.assertNotIn("msiexec", script)
        self.assertNotIn("winetricks --unattended powershell_core", script)


if __name__ == "__main__":
    unittest.main()
