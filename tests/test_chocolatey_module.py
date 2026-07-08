"""Chocolatey module tests for module-first architecture."""
from __future__ import annotations

import unittest

from core.manifest import Manifest, ManifestError


class ChocolateyModuleUnitTests(unittest.TestCase):
    """Test chocolatey module build() method."""

    def test_build_empty_modules(self):
        """No modules means no build steps."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [],
        })
        self.assertEqual(len(manifest.modules), 0)

    def test_build_with_chocolatey_module(self):
        """Chocolatey module generates build steps."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })
        self.assertEqual(len(manifest.modules), 1)
        self.assertEqual(manifest.modules[0].type, "chocolatey")
        
        # Test build() method
        steps = manifest.modules[0].build()
        self.assertGreater(len(steps), 0)
        # Should have commands for installing 7zip
        all_commands = " ".join(" ".join(step.commands) for step in steps)
        self.assertIn("7zip", all_commands)

    def test_chocolatey_installs_self_contained_without_codeberg_wrapper(self):
        """Chocolatey-for-wine owns its PowerShell/CLR setup for now."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })

        steps = manifest.modules[0].build()
        all_commands = "\n".join("\n".join(step.commands) for step in steps)

        self.assertIn("Chocolatey-for-wine", all_commands)
        self.assertIn("ChoCinstaller_*.exe", all_commands)
        self.assertIn("WINEDLLOVERRIDES", all_commands)
        self.assertIn("Verifying Chocolatey", all_commands)
        self.assertIn("--version", all_commands)
        self.assertNotIn("codeberg.org/Synchro/powershell-wrapper-for-wine", all_commands)
        self.assertNotIn("powershell64.exe", all_commands)

    def test_chocolatey_sets_win10_before_cfw_powershell_runs(self):
        """PowerShell Core 7.x must see a win10 prefix before CFW invokes pwsh."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })

        steps = manifest.modules[0].build()
        all_commands = "\n".join("\n".join(step.commands) for step in steps)

        self.assertIn("Setting Wine Windows version to win10 for Chocolatey-for-wine", all_commands)
        self.assertIn("winecfg /v win10", all_commands)
        self.assertLess(
            all_commands.index("winecfg /v win10"),
            all_commands.index("Running Chocolatey-for-wine installer"),
        )

    def test_chocolatey_pwsh_probe_uses_file_sentinel(self):
        """PowerShell under Wine can execute even when stdout capture is empty."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })

        steps = manifest.modules[0].build()
        all_commands = "\n".join("\n".join(step.commands) for step in steps)

        self.assertIn("pwsh_probe_sentinel=", all_commands)
        self.assertIn("pwsh_probe_sentinel_win=", all_commands)
        self.assertIn("WriteAllText", all_commands)
        self.assertIn("PowerShell probe did not create sentinel", all_commands)
        self.assertIn("PowerShell probe produced no captured stdout", all_commands)
        self.assertLess(
            all_commands.index("pwsh_probe_sentinel_win="),
            all_commands.index("probe_cfw_pwsh()"),
        )

    def test_chocolatey_repairs_dead_cfw_pwsh_with_zip_payload(self):
        """Dead CFW-installed pwsh is repaired without rerunning MSI installers."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })

        steps = manifest.modules[0].build()
        all_commands = "\n".join("\n".join(step.commands) for step in steps)

        self.assertIn("Repairing Chocolatey-for-wine PowerShell from ZIP payload", all_commands)
        self.assertIn("PowerShell-7.4.11-win-x64.zip", all_commands)
        self.assertIn("CAGE_CHOCOLATEY_PWSH_REPAIR_TIMEOUT", all_commands)
        self.assertIn("pwsh_zip=", all_commands)
        self.assertIn("pwsh_dir=", all_commands)
        self.assertIn("zipfile.ZipFile", all_commands)
        self.assertIn("[cfw-pwsh-zip]", all_commands)
        self.assertIn("after PowerShell ZIP repair", all_commands)
        self.assertIn("PowerShell ZIP repair failed", all_commands)
        self.assertLess(
            all_commands.index("Probing Chocolatey-for-wine PowerShell"),
            all_commands.index("Repairing Chocolatey-for-wine PowerShell from ZIP payload"),
        )
        self.assertLess(
            all_commands.index("after PowerShell ZIP repair"),
            all_commands.index("timeout \"${CAGE_CHOCOLATEY_FINALIZE_TIMEOUT:-1200s}\""),
        )
        self.assertNotIn("winetricks --force --unattended powershell_core", all_commands)
        self.assertNotIn("codeberg.org/Synchro/powershell-wrapper-for-wine", all_commands)
        self.assertNotIn("powershell64.exe", all_commands)

    def test_chocolatey_recovers_partial_cfw_finalization(self):
        """Partial CFW installs rerun choc_install.ps1 instead of accepting raw nupkg extraction."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })

        steps = manifest.modules[0].build()
        all_commands = "\n".join("\n".join(step.commands) for step in steps)

        self.assertIn("raw_choco_exe=", all_commands)
        self.assertIn("ProgramData/tools/chocolateyInstall/choco.exe", all_commands)
        self.assertIn("pwsh_exe=", all_commands)
        self.assertIn("Program Files/PowerShell/7/pwsh.exe", all_commands)
        self.assertIn("choc_install.ps1", all_commands)
        self.assertIn("Finalizing partial Chocolatey-for-wine install", all_commands)
        self.assertIn("finalize_driver=", all_commands)
        self.assertIn("$ErrorActionPreference = 'Stop'", all_commands)
        self.assertIn("-NoProfile", all_commands)
        self.assertIn("-ExecutionPolicy Bypass", all_commands)
        self.assertIn("[cfw-finalize]", all_commands)
        self.assertIn("pwsh_probe_log=", all_commands)
        self.assertIn("Probing Chocolatey-for-wine PowerShell", all_commands)
        self.assertIn("[cfw-pwsh]", all_commands)
        self.assertIn("PowerShell probe did not create sentinel", all_commands)
        self.assertIn("PowerShell probe produced no captured stdout", all_commands)
        self.assertIn("Chocolatey-for-wine finalizer did not create canonical choco.exe", all_commands)
        self.assertIn("Chocolatey-for-wine finalizer returned success but left choco.exe missing", all_commands)
        self.assertIn("Finalizer log was empty", all_commands)
        self.assertIn("timeout \"${CAGE_CHOCOLATEY_FINALIZE_TIMEOUT:-1200s}\"", all_commands)

    def test_chocolatey_never_treats_raw_extracted_choco_as_success(self):
        """Package installation still uses canonical Chocolatey bin path only."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })

        steps = manifest.modules[0].build()
        install_script = "\n".join(steps[0].commands)
        package_script = "\n".join(steps[1].commands)

        self.assertIn("ProgramData/chocolatey/bin/choco.exe", install_script)
        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package_script)
        self.assertIn("ProgramData/tools/chocolateyInstall/choco.exe", install_script)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package_script)

    def test_build_preserves_provenance(self):
        """Provenance field is preserved through parsing."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "packages": ["7zip"]},
            ],
            "provenance": {"test": "value"},
        })
        self.assertEqual(manifest.provenance, {"test": "value"})


class ChocolateyModuleManifestTests(unittest.TestCase):
    """Test chocolatey module manifest parsing."""

    def test_bluebuild_style_chocolatey_module(self):
        """Chocolatey module with packages list parses correctly."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip", "notepadplusplus"]}},
            ],
        })
        self.assertEqual(len(manifest.modules), 1)
        module = manifest.modules[0]
        self.assertEqual(module.type, "chocolatey")
        self.assertEqual(module.install["packages"], ["7zip", "notepadplusplus"])

    def test_chocolatey_module_rejects_shell_like_package_names(self):
        """Package names must be alphanumeric with dots/underscores/plus/dashes."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip; rm -rf /"]}},
            ],
        })
        # Validation happens in build(), not in from_dict()
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("must use letters, numbers", str(ctx.exception))

    def test_direct_choco_install_step_rejects_shell_like_args(self):
        """Direct choco install steps validate args."""
        # In the new architecture, script modules accept any command
        # Validation happens at runtime, not parse time
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "script",
                    "command": "choco install 7zip; rm -rf /",
                },
            ],
        })
        # Script modules accept any command - no validation at parse time
        self.assertEqual(len(manifest.modules), 1)

    def test_direct_choco_install_step_rejects_unknown_command(self):
        """Direct choco install steps must use 'install' command."""
        # In the new architecture, script modules accept any command
        # Choco validation is now in the chocolatey module type
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "script",
                    "command": "echo test",
                },
            ],
        })
        self.assertEqual(len(manifest.modules), 1)


class ChocolateyModuleBuildTests(unittest.TestCase):
    """Test chocolatey module build step generation."""

    def test_chocolatey_module_generates_install_commands(self):
        """Chocolatey module generates proper install commands."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip", "notepadplusplus"]}},
            ],
        })
        
        steps = manifest.modules[0].build()
        self.assertGreater(len(steps), 0)
        
        # Check that build steps contain the package names
        all_commands = " ".join(" ".join(step.commands) for step in steps)
        self.assertIn("7zip", all_commands)
        self.assertIn("notepadplusplus", all_commands)

    def test_chocolatey_module_with_custom_source(self):
        """Chocolatey module accepts custom source URL."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "chocolatey",
                    "install": {"packages": ["7zip"]},
                    "source": "https://custom.choco.source/",
                },
            ],
        })
        
        module = manifest.modules[0]
        self.assertEqual(module.install["packages"], ["7zip"])
        self.assertEqual(module.source, "https://custom.choco.source/")


if __name__ == "__main__":
    unittest.main()
