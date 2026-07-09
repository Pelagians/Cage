"""Chocolatey module tests."""
from __future__ import annotations

import unittest

from core.manifest import Manifest


def _manifest(packages=None, **module_overrides):
    module = {"type": "chocolatey", "install": {"packages": packages or ["7zip"]}}
    module.update(module_overrides)
    return Manifest.from_dict({
        "schemaVersion": "cage.app/v0",
        "name": "test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "latest"},
        "modules": [module],
        "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
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
            "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
        })
        self.assertEqual(manifest.modules, [])

    def test_chocolatey_module_parses_and_preserves_provenance(self):
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip", "notepadplusplus"]}}],
            "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
            "provenance": {"test": "value"},
        })

        self.assertEqual(manifest.modules[0].type, "chocolatey")
        self.assertEqual(manifest.modules[0].install["packages"], ["7zip", "notepadplusplus"])
        self.assertEqual(manifest.provenance, {"test": "value"})

    def test_chocolatey_module_claims_self_contained_capability_slots(self):
        capabilities = _manifest().modules[0].capabilities()

        self.assertEqual(capabilities["engine"], "chocolatey-powershell-msi")
        self.assertEqual(capabilities["winps-shim"], "chocolatey-native")
        self.assertEqual(capabilities["shim-library"], "chocolatey-for-wine")

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

    def test_chocolatey_builds_sequential_upstream_derived_steps(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        descriptions = [step.description for step in steps]
        script = _all_commands(steps)

        self.assertEqual(descriptions, [
            "Install PowerShell 7 MSI for Chocolatey",
            "Prepare Chocolatey-for-wine data",
            "Install .NET Framework 4.8 for Chocolatey",
            "Prepare Wine registry for Chocolatey",
            "Promote Chocolatey natively",
            "Diagnose Chocolatey readiness",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        self.assertNotIn('wine "$cfw_installer" /s /q', script)
        self.assertNotIn("Install Chocolatey-for-wine via upstream ChoCinstaller", script)
        self.assertLess(script.index("Prepare Chocolatey-for-wine data"), script.index("Promote Chocolatey natively"))
        self.assertLess(script.index("Promote Chocolatey natively"), script.index("Diagnose Chocolatey readiness"))
        self.assertLess(script.index("Diagnose Chocolatey readiness"), script.index("Install Chocolatey packages"))

    def test_chocolatey_uses_pinned_powershell_msi_like_upstream_chocinstaller(self):
        powershell = "\n".join(_manifest().modules[0].build()[0].commands)

        self.assertIn("PowerShell-7.5.5-win-x64.msi", powershell)
        self.assertIn("https://github.com/PowerShell/PowerShell/releases/download/v7.5.5/PowerShell-7.5.5-win-x64.msi", powershell)
        self.assertIn("b2ac56b7639e2b259bb78bab077555d76f2a5eec6c516690d63de36bc1d6ca25", powershell)
        self.assertIn("actual_pwsh_msi_sha", powershell)
        self.assertIn("pwsh_msi_win=\"$(winepath -w \"$pwsh_msi\")\"", powershell)
        self.assertIn("powershell-msiexec.log", powershell)
        self.assertIn("wine msiexec /i \"$pwsh_msi_win\"", powershell)
        self.assertIn("/QN", powershell)
        self.assertIn("/NORESTART", powershell)
        self.assertIn("CAGE_POWERSHELL_MSI_TIMEOUT", powershell)
        self.assertIn("634F4903-28DC-4BA6-A39F-4B3E394D4E36", powershell)
        self.assertNotIn("16735AF7-1D8D-3681-94A5-C578A61EC832", powershell)
        self.assertIn('test -f "$pwsh_exe"', powershell)
        self.assertIn('chmod +x "$pwsh_exe"', powershell)
        self.assertNotIn("PowerShell-7.4.11-win-x64.zip", powershell)
        self.assertNotIn("zipfile.ZipFile", powershell)

    def test_chocolatey_extracts_nupkg_to_raw_tools_before_promotion(self):
        steps = _manifest().modules[0].build()
        prepare = "\n".join(steps[1].commands)
        promote = "\n".join(steps[4].commands)

        self.assertIn("https://community.chocolatey.org/api/v2/package/chocolatey/2.6.0", prepare)
        self.assertIn("f13a2af9cd4ec2c9b58d81861bc95ad7151e3a871d8f758dffa72a996a3792d8", prepare)
        self.assertIn("actual_choco_nupkg_sha", prepare)
        self.assertIn("zipfile.ZipFile", prepare)
        self.assertIn("ProgramData/tools/ChocolateyInstall", prepare)
        self.assertIn("tools/chocolateyInstall/", prepare)
        self.assertIn("choc_install.ps1", prepare)
        self.assertIn('member.filename.replace("\\\\", "/")', prepare)
        self.assertLess(_all_commands(steps).index("Prepare Chocolatey-for-wine data"), _all_commands(steps).index("Promote Chocolatey natively"))
        self.assertIn("ProgramData/tools/ChocolateyInstall/choco.exe", promote)

    def test_chocolatey_prepare_matches_release_archive_layout(self):
        """Pinned CFW release archive does not include winetricks.ps1."""
        prepare = "\n".join(_manifest().modules[0].build()[1].commands)

        self.assertIn('cfw_extract="$cfw_cache/extracted/Chocolatey-for-wine"', prepare)
        self.assertIn('test -f "$cfw_extract/choc_install.ps1"', prepare)
        self.assertIn('test -f "$cfw_extract/c_drive.7z"', prepare)
        self.assertIn('cfw_c_drive_extract="$cfw_cache/c_drive-extracted"', prepare)
        self.assertIn('extract_7z_archive "$cfw_extract/c_drive.7z" "$cfw_c_drive_extract"', prepare)
        self.assertIn('source_root = extract_root / "c:"', prepare)
        self.assertIn('drive_c / "c:"', prepare)
        self.assertNotIn('extract_7z_archive "$cfw_extract/c_drive.7z" "$wine_prefix/drive_c"', prepare)
        self.assertIn("https://raw.githubusercontent.com/PietJankbal/Chocolatey-for-wine/v0.5c.755/winetricks.ps1", prepare)
        self.assertIn("1d74ffad96f2052d42a0fa3c7ac5dbc8d099e7ad9f9aba3213446a25b34ff48c", prepare)
        self.assertIn("actual_cfw_winetricks_sha", prepare)
        self.assertIn('cp -f "$cfw_winetricks_ps1" "$cfw_prefix_dir/winetricks.ps1"', prepare)
        self.assertNotIn('test -f "$cfw_extract/winetricks.ps1"', prepare)
        self.assertNotIn('cp -f "$cfw_extract/winetricks.ps1"', prepare)

    def test_chocolatey_dotnet48_installs_x86_and_x64_msi_steps(self):
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
        self.assertIn("netfx_Full_x86.msi", dotnet)
        self.assertIn("netfx_Full_x64.msi", dotnet)
        self.assertNotIn("dotnet_extract=\"$dotnet_cache/extracted\"", dotnet)
        self.assertIn("dotnet48-$label-msiexec.log", dotnet)
        self.assertIn("install_dotnet_msi x86", dotnet)
        self.assertIn("install_dotnet_msi x64", dotnet)
        self.assertLess(dotnet.index("install_dotnet_msi x64"), dotnet.index("install_dotnet_msi x86"))
        self.assertIn("wine msiexec /i \"$netfx_msi_win\"", dotnet)
        self.assertIn("/QN", dotnet)
        self.assertIn("MSIFASTINSTALL=2", dotnet)
        self.assertIn("DISABLEROLLBACK=1", dotnet)
        self.assertIn("/L*v", dotnet)
        self.assertIn("Return value 3", dotnet)
        self.assertIn("Action ended .*INSTALL[.] Return value 1", dotnet)
        self.assertIn("dotnet_msi_success=", dotnet)
        self.assertIn("dotnet_marker_success=", dotnet)
        self.assertIn("already has native CLR markers; skipping MSI install", dotnet)
        self.assertIn("MSI did not report INSTALL success, but required native CLR markers exist; continuing", dotnet)
        self.assertIn("MSI log reports INSTALL success; ignoring Wine msiexec exit", dotnet)
        self.assertIn("CAGE_DOTNET48_TIMEOUT", dotnet)
        self.assertIn("windows/syswow64/mscoree.dll", dotnet)
        self.assertIn("windows/system32/mscoree.dll", dotnet)
        self.assertIn("windows/Microsoft.NET/Framework/v4.0.30319/clr.dll", dotnet)
        self.assertIn("windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll", dotnet)
        self.assertNotIn("marker missing after MSI step", dotnet)
        self.assertEqual(dotnet.count("wine msiexec"), 1)
        self.assertEqual(dotnet.count("install_dotnet_msi "), 2)
        self.assertNotIn("PowerShell", dotnet)
        self.assertNotIn("choco.exe install", dotnet)

    def test_chocolatey_registry_prep_sets_win10_and_upstream_dll_policy(self):
        registry = "\n".join(_manifest().modules[0].build()[3].commands)

        self.assertIn("winecfg /v win10", registry)
        self.assertIn("CAGE_WINECFG_TIMEOUT", registry)
        self.assertIn("CAGE_WINE_REG_TIMEOUT", registry)
        self.assertIn("HKCU\\Software\\Wine\\DllOverrides", registry)
        self.assertIn("/v mscoree /t REG_SZ /d native /f", registry)
        self.assertIn("HKLM\\Software\\Microsoft\\.NETFramework", registry)
        self.assertIn("/v OnlyUseLatestCLR /t REG_DWORD /d 1 /f", registry)
        self.assertIn("AppDefaults\\pwsh.exe\\DllOverrides", registry)
        self.assertIn("AppDefaults\\choco.exe\\DllOverrides", registry)
        self.assertIn('/v amsi /d "" /f', registry)
        self.assertIn('/v dwmapi /d "" /f', registry)
        self.assertIn("/v rpcrt4 /d native,builtin /f", registry)
        self.assertIn("AppDefaults\\choco.exe\\DllOverrides' /v mscoree /t REG_SZ /d native /f", registry)
        self.assertIn("HKCU\\Environment", registry)
        self.assertIn("/v PS7", registry)
        self.assertIn("C:\\Program Files\\PowerShell\\7\\pwsh.exe", registry)

    def test_chocolatey_native_promotion_replaces_pwsh_finalizer_boundary(self):
        promote = "\n".join(_manifest().modules[0].build()[4].commands)

        self.assertIn("Promote Chocolatey natively", promote)
        self.assertIn('raw_choco_dir="$wine_prefix/drive_c/ProgramData/tools/ChocolateyInstall"', promote)
        self.assertIn('canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"', promote)
        self.assertIn('canonical_bin_dir="$canonical_choco_dir/bin"', promote)
        self.assertIn('test -f "$raw_choco_exe"', promote)
        self.assertIn("shutil.copytree", promote)
        self.assertIn("Native Chocolatey promotion copied raw payload", promote)
        self.assertNotIn("pwsh_probe_script=", promote)
        self.assertNotIn("finalize_driver=", promote)
        self.assertNotIn("choc_install.patched.ps1", promote)
        self.assertNotIn('wine "$pwsh_exe_win"', promote)
        self.assertNotIn("PWSH-ALIVE", promote)

    def test_chocolatey_native_promotion_preserves_payload_and_creates_bin_redirects(self):
        promote = "\n".join(_manifest().modules[0].build()[4].commands)

        self.assertIn('rm -rf "$canonical_choco_dir"', promote)
        self.assertIn('source = Path(sys.argv[1])', promote)
        self.assertIn('dest = Path(sys.argv[2])', promote)
        self.assertIn('redirects = dest / "redirects"', promote)
        self.assertIn('bin_dir = dest / "bin"', promote)
        self.assertIn('shutil.copy2(item, bin_dir / item.name)', promote)
        self.assertIn('choco = bin_dir / "choco.exe"', promote)
        self.assertIn('root_choco = dest / "choco.exe"', promote)
        self.assertIn("helpers", promote)
        self.assertIn("tools", promote)
        self.assertIn("redirects", promote)

    def test_chocolatey_native_promotion_sets_environment_without_pwsh(self):
        promote = "\n".join(_manifest().modules[0].build()[4].commands)

        self.assertIn("ChocolateyInstall", promote)
        self.assertIn("ChocolateyToolsLocation", promote)
        self.assertIn("C:\\ProgramData\\chocolatey", promote)
        self.assertIn("C:\\tools", promote)
        self.assertIn("wine reg add 'HKCU\\Environment'", promote)
        self.assertNotIn("WindowsPowerShell/v1.0/powershell.exe", promote)
        self.assertNotIn("pwsh_exe=", promote)
        self.assertNotIn("export PS7=", promote)
        self.assertNotIn("export WINEPATH=", promote)

    def test_chocolatey_native_promotion_keeps_canonical_choco_gate(self):
        promote = "\n".join(_manifest().modules[0].build()[4].commands)

        self.assertIn("ProgramData/tools/ChocolateyInstall/choco.exe", promote)
        self.assertIn("ProgramData/chocolatey/bin/choco.exe", promote)
        self.assertIn("raw ChocolateyInstall payload is only a source", promote)
        self.assertIn("ERROR: native Chocolatey promotion did not create canonical choco.exe", promote)
        self.assertIn("CAGE_CHOCOLATEY_VERIFY_TIMEOUT", promote)
        self.assertIn('timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" --version', promote)
        self.assertIn("export ChocolateyInstall=", promote)
        self.assertIn("export ChocolateyToolsLocation=", promote)
        self.assertIn("mscoree=n", promote)
        self.assertIn("logs/chocolatey-verify.log", promote)
        self.assertIn("canonical Chocolatey verification failed", promote)
        self.assertIn("Continuing to diagnostic step", promote)
        self.assertNotIn("Chocolatey-for-wine finalizer did not create canonical choco.exe", promote)
        self.assertNotIn("CAGE_CHOCOLATEY_FINALIZE_TIMEOUT", promote)

    def test_chocolatey_package_install_uses_canonical_choco_only(self):
        package = "\n".join(_manifest(["7zip", "notepadplusplus"]).modules[0].build()[6].commands)

        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("CAGE_CHOCOLATEY_INSTALL_TIMEOUT", package)
        self.assertIn("feature disable --name=powershellHost", package)
        self.assertIn("feature enable -n allowGlobalConfirmation", package)
        self.assertIn("chocolatey-feature-powershellHost.log", package)
        self.assertIn("chocolatey-feature-allowGlobalConfirmation.log", package)
        self.assertLess(package.index("feature disable --name=powershellHost"), package.index("wine \"$choco_exe\" install 7zip notepadplusplus -y"))
        self.assertLess(package.index("feature enable -n allowGlobalConfirmation"), package.index("wine \"$choco_exe\" install 7zip notepadplusplus -y"))
        self.assertIn("wine \"$choco_exe\" install 7zip notepadplusplus -y", package)
        self.assertIn("choco_diag_status", package)
        self.assertIn("export ChocolateyInstall=", package)
        self.assertIn("export ChocolateyToolsLocation=", package)
        self.assertIn("mscoree=n", package)
        self.assertNotIn("unset WINEDLLOVERRIDES", package)

    def test_chocolatey_diagnostic_writes_json_before_package_install(self):
        steps = _manifest(["7zip"]).modules[0].build()
        diagnostic = "\n".join(steps[5].commands)
        package = "\n".join(steps[6].commands)

        self.assertIn("metadata/chocolatey-diagnostic.json", diagnostic)
        self.assertIn("cage.chocolatey-diagnostic/v0", diagnostic)
        self.assertIn("canonicalChocoExists", diagnostic)
        self.assertIn("rawToolsPayloadExists", diagnostic)
        self.assertIn("winepathCanonical", diagnostic)
        self.assertIn("registryEnvironment", diagnostic)
        self.assertIn("wineDllOverridesMscoree", diagnostic)
        self.assertIn("dotnetReleaseRegistry", diagnostic)
        self.assertIn("nativeMscoreeExists", diagnostic)
        self.assertIn("nativeMscoreeiExists", diagnostic)
        self.assertIn("nativeClrExists", diagnostic)
        self.assertIn("nativeWow64MscoreeExists", diagnostic)
        self.assertIn("nativeWow64MscoreeiExists", diagnostic)
        self.assertIn("nativeWow64ClrExists", diagnostic)
        self.assertIn("chocoVersion", diagnostic)
        self.assertIn("wineCmdEcho", diagnostic)
        self.assertIn("chocoVersionViaCmd", diagnostic)
        self.assertIn("choco-version-winedebug.log", diagnostic)
        self.assertIn("choco-mscoree-loader.log", diagnostic)
        self.assertIn("sourceList", diagnostic)
        self.assertIn("export ChocolateyInstall=", diagnostic)
        self.assertIn("export ChocolateyToolsLocation=", diagnostic)
        self.assertIn("mscoree=n", diagnostic)
        self.assertIn('json.dumps(payload, indent=2, sort_keys=True) + "\\n"', diagnostic)
        self.assertNotIn('json.dumps(payload, indent=2, sort_keys=True) + "\n"', diagnostic)
        self.assertLess(_all_commands(steps).index("Diagnose Chocolatey readiness"), _all_commands(steps).index("Install Chocolatey packages"))
        self.assertIn("choco_diag_status", package)

    def test_chocolatey_module_rejects_non_string_package_names(self):
        manifest = _manifest(["7zip", 42])

        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()

        self.assertIn("install.packages", str(ctx.exception))

    def test_direct_script_module_still_accepts_arbitrary_commands(self):
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [{"type": "script", "command": "choco install 7zip; rm -rf /"}],
            "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
        })

        self.assertEqual(len(manifest.modules), 1)
        self.assertTrue(manifest.modules[0].build()[0].unsafe)


if __name__ == "__main__":
    unittest.main()
