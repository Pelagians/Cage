"""Chocolatey module tests for deterministic module-first architecture."""
from __future__ import annotations

import unittest

from core.manifest import Manifest


def _manifest(packages: list[str] | None = None, **module_overrides):
    module = {"type": "chocolatey", "install": {"packages": packages or ["7zip"]}}
    module.update(module_overrides)
    return Manifest.from_dict({
        "schemaVersion": "cage.app/v0",
        "name": "test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "latest"},
        "modules": [module],
    })


def _all_commands(steps) -> str:
    return "\n".join("\n".join(step.commands) for step in steps)


class ChocolateyModuleUnitTests(unittest.TestCase):
    def test_empty_modules_parse(self):
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [],
        })
        self.assertEqual(manifest.modules, [])

    def test_chocolatey_module_parses_and_preserves_provenance(self):
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip", "notepadplusplus"]}}],
            "provenance": {"test": "value"},
        })

        self.assertEqual(manifest.modules[0].type, "chocolatey")
        self.assertEqual(manifest.modules[0].install["packages"], ["7zip", "notepadplusplus"])
        self.assertEqual(manifest.provenance, {"test": "value"})

    def test_chocolatey_module_rejects_shell_like_package_names(self):
        manifest = _manifest(["7zip; rm -rf /"])

        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()

        self.assertIn("must use letters, numbers", str(ctx.exception))

    def test_chocolatey_module_accepts_custom_source_url(self):
        manifest = _manifest(source="https://custom.choco.source/")

        self.assertEqual(manifest.modules[0].source, "https://custom.choco.source/")
        script = _all_commands(manifest.modules[0].build())
        self.assertIn(" -s 'https://custom.choco.source/'", script)

    def test_chocolatey_builds_sequential_verifiable_steps_without_chocinstaller(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        descriptions = [step.description for step in steps]
        script = _all_commands(steps)

        self.assertEqual(descriptions, [
            "Install PowerShell 7 engine",
            "Prepare Chocolatey-for-wine data",
            "Install .NET Framework 4.8 for Chocolatey",
            "Prepare Wine registry for Chocolatey",
            "Finalize Chocolatey-for-wine",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        self.assertNotIn("ChoCinstaller", script)
        self.assertNotIn("Running Chocolatey-for-wine installer", script)
        self.assertNotIn("Repairing Chocolatey-for-wine PowerShell", script)
        self.assertNotIn("winetricks --force --unattended powershell_core", script)
        self.assertNotIn("winetricks --unattended powershell_core", script)
        self.assertNotIn("codeberg.org/Synchro/powershell-wrapper-for-wine", script)

    def test_chocolatey_extracts_nupkg_to_raw_tools_before_finalizer(self):
        steps = _manifest().modules[0].build()
        prepare = "\n".join(steps[1].commands)
        finalize = "\n".join(steps[4].commands)

        self.assertIn("https://community.chocolatey.org/api/v2/package/chocolatey/2.6.0", prepare)
        self.assertIn("f13a2af9cd4ec2c9b58d81861bc95ad7151e3a871d8f758dffa72a996a3792d8", prepare)
        self.assertIn("actual_choco_nupkg_sha", prepare)
        self.assertIn("zipfile.ZipFile", prepare)
        self.assertIn("ProgramData/tools/ChocolateyInstall", prepare)
        self.assertIn("tools/chocolateyInstall/", prepare)
        self.assertIn("choc_install.ps1", prepare)
        self.assertIn('member.filename.replace("\\\\", "/")', prepare)
        self.assertLess(_all_commands(steps).index("Prepare Chocolatey-for-wine data"), _all_commands(steps).index("Finalize Chocolatey-for-wine"))
        self.assertIn("ProgramData/tools/ChocolateyInstall/choco.exe", finalize)

    def test_chocolatey_prepare_matches_release_archive_layout(self):
        """Pinned CFW release archive does not include winetricks.ps1."""
        prepare = "\n".join(_manifest().modules[0].build()[1].commands)

        self.assertIn('cfw_extract="$cfw_cache/extracted/Chocolatey-for-wine"', prepare)
        self.assertIn('test -f "$cfw_extract/choc_install.ps1"', prepare)
        self.assertIn('test -f "$cfw_extract/c_drive.7z"', prepare)
        self.assertIn("https://raw.githubusercontent.com/PietJankbal/Chocolatey-for-wine/v0.5c.755/winetricks.ps1", prepare)
        self.assertIn("1d74ffad96f2052d42a0fa3c7ac5dbc8d099e7ad9f9aba3213446a25b34ff48c", prepare)
        self.assertIn("actual_cfw_winetricks_sha", prepare)
        self.assertIn('cp -f "$cfw_winetricks_ps1" "$cfw_prefix_dir/winetricks.ps1"', prepare)
        self.assertNotIn('test -f "$cfw_extract/winetricks.ps1"', prepare)
        self.assertNotIn('cp -f "$cfw_extract/winetricks.ps1"', prepare)

    def test_chocolatey_dotnet48_is_dedicated_single_msi_step(self):
        dotnet = "\n".join(_manifest().modules[0].build()[2].commands)

        self.assertIn("https://go.microsoft.com/fwlink/?linkid=2088631", dotnet)
        self.assertIn("0a3a390c47e639d0f7fc65b21195fee6b7f65b066f80f70c60fab191d14b7e40", dotnet)
        self.assertIn("actual_ndp48_sha", dotnet)
        self.assertIn("setupcache=\"$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/SetupCache\"", dotnet)
        self.assertIn("dotnet_extract=\"$setupcache/v4.8.03761\"", dotnet)
        self.assertIn("-x!\"*.cab\"", dotnet)
        self.assertIn("-x!\"netfx_c*\"", dotnet)
        self.assertIn("-x!\"netfx_e*\"", dotnet)
        self.assertIn("-x!\"NetFx4*\"", dotnet)
        self.assertIn("netfx_Full_x64.msi", dotnet)
        self.assertNotIn("dotnet_extract=\"$dotnet_cache/extracted\"", dotnet)
        self.assertIn("netfx_msi_win=\"$(winepath -w \"$netfx_msi\")\"", dotnet)
        self.assertIn("dotnet48-msiexec.log", dotnet)
        self.assertIn("msiexec", dotnet)
        self.assertIn("/i \"$netfx_msi_win\"", dotnet)
        self.assertIn("/QN", dotnet)
        self.assertIn("MSIFASTINSTALL=2", dotnet)
        self.assertIn("DISABLEROLLBACK=1", dotnet)
        self.assertIn("/L*v", dotnet)
        self.assertIn("Return value 3", dotnet)
        self.assertIn("Action ended .*INSTALL[.] Return value 1", dotnet)
        self.assertIn("dotnet_msi_success=", dotnet)
        self.assertIn("MSI log reports INSTALL success; ignoring Wine msiexec exit", dotnet)
        self.assertIn("CAGE_DOTNET48_TIMEOUT", dotnet)
        self.assertNotIn("marker missing after MSI step", dotnet)
        self.assertEqual(dotnet.count("wine msiexec"), 1)
        self.assertNotIn("PowerShell", dotnet)
        self.assertNotIn("choco.exe install", dotnet)

    def test_chocolatey_registry_prep_sets_win10_and_pwsh_appdefaults(self):
        registry = "\n".join(_manifest().modules[0].build()[3].commands)

        self.assertIn("winecfg /v win10", registry)
        self.assertIn("CAGE_WINECFG_TIMEOUT", registry)
        self.assertIn("CAGE_WINE_REG_TIMEOUT", registry)
        self.assertIn("AppDefaults\\pwsh.exe\\DllOverrides", registry)
        self.assertIn('/v amsi /d "" /f', registry)
        self.assertIn('/v dwmapi /d "" /f', registry)
        self.assertIn("/v rpcrt4 /d native,builtin /f", registry)

    def test_chocolatey_finalizer_uses_verified_pwsh_and_canonical_choco(self):
        finalize = "\n".join(_manifest().modules[0].build()[4].commands)

        self.assertIn("pwsh_exe=", finalize)
        self.assertIn("Program Files/PowerShell/7/pwsh.exe", finalize)
        self.assertIn("pwsh_probe_sentinel=", finalize)
        self.assertIn("WriteAllText", finalize)
        self.assertIn("PowerShell probe did not create sentinel", finalize)
        self.assertIn("choc_install.ps1", finalize)
        self.assertIn("finalize_driver=", finalize)
        self.assertIn("Skipping upstream ucrtbase_clr0400.dll wait", finalize)
        self.assertIn("choc_install.patched.ps1", finalize)
        self.assertIn("$ErrorActionPreference = 'Stop'", finalize)
        self.assertIn("finalize_rc=", finalize)
        self.assertIn("[cfw-finalize]", finalize)
        self.assertIn("ProgramData/chocolatey/bin/choco.exe", finalize)
        self.assertIn("Chocolatey-for-wine finalizer did not create canonical choco.exe", finalize)
        self.assertIn("CAGE_CHOCOLATEY_FINALIZE_TIMEOUT", finalize)

    def test_chocolatey_package_install_uses_canonical_choco_only(self):
        package = "\n".join(_manifest(["7zip", "notepadplusplus"]).modules[0].build()[5].commands)

        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("wine \"$choco_exe\" install 7zip notepadplusplus -y", package)
        self.assertIn("unset WINEDLLOVERRIDES", package)

    def test_direct_script_module_still_accepts_arbitrary_commands(self):
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [{"type": "script", "command": "choco install 7zip; rm -rf /"}],
        })

        self.assertEqual(len(manifest.modules), 1)


if __name__ == "__main__":
    unittest.main()
