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


def _commands_for(steps, description: str) -> str:
    matches = [step for step in steps if step.description == description]
    if len(matches) != 1:
        raise AssertionError(f"expected one step named {description!r}, found {len(matches)}")
    return "\n".join(matches[0].commands)


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
            "Record Chocolatey bootstrap profile",
            "Install PowerShell 7 MSI for Chocolatey",
            "Prepare Chocolatey-for-wine data",
            "Install native .NET loader",
            "Install frozen dotnet481 profile",
            "Prepare Wine registry for Chocolatey",
            "Install Chocolatey PowerShell wrapper",
            "Promote Chocolatey natively",
            "Diagnose Chocolatey readiness",
            "Apply Chocolatey feature policy",
            "Prove Chocolatey local package lifecycle",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        self.assertNotIn('wine "$cfw_installer" /s /q', script)
        self.assertNotIn("Install Chocolatey-for-wine via upstream ChoCinstaller", script)
        self.assertLess(script.index("Prepare Chocolatey-for-wine data"), script.index("Promote Chocolatey natively"))
        self.assertLess(script.index("Promote Chocolatey natively"), script.index("Diagnose Chocolatey readiness"))
        self.assertLess(script.index("Diagnose Chocolatey readiness"), script.index("Apply Chocolatey feature policy"))
        self.assertLess(script.index("Apply Chocolatey feature policy"), script.index("Prove Chocolatey local package lifecycle"))
        self.assertLess(script.index("Prove Chocolatey local package lifecycle"), script.index("Install Chocolatey packages"))

    def test_chocolatey_uses_pinned_powershell_msi_like_upstream_chocinstaller(self):
        powershell = _commands_for(_manifest().modules[0].build(), "Install PowerShell 7 MSI for Chocolatey")

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
        prepare = _commands_for(steps, "Prepare Chocolatey-for-wine data")
        promote = _commands_for(steps, "Promote Chocolatey natively")

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
        prepare = _commands_for(_manifest().modules[0].build(), "Prepare Chocolatey-for-wine data")

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

    def test_chocolatey_dotnet481_uses_upstream_manifest_payload(self):
        dotnet = _commands_for(_manifest().modules[0].build(), "Install frozen dotnet481 profile")

        self.assertIn("ndp481-x86-x64-allos-enu.exe", dotnet)
        self.assertIn("https://download.visualstudio.microsoft.com/download/pr/6f083c7e-bd40-44d4-9e3f-ffba71ec8b09/3951fd5af6098f2c7e8ff5c331a0679c/ndp481-x86-x64-allos-enu.exe", dotnet)
        self.assertIn("859b556ee19a33353626682b8b6f7e9ce97cd325b0d8f24c7770dc31f688d3c1", dotnet)
        self.assertIn("actual_ndp481_sha", dotnet)
        self.assertIn("x64-Windows10.0-KB5011048-x64.cab", dotnet)
        self.assertIn('"amd64*/*" "x86*/*" "wow64*/*" "*.manifest"', dotnet)
        self.assertIn("dotnet481_manifest_payload", dotnet)
        self.assertIn("install_manifest_files", dotnet)
        self.assertIn("write_manifest_registry", dotnet)
        self.assertIn("reg_keys64.reg", dotnet)
        self.assertIn("reg_keys32.reg", dotnet)
        self.assertIn("wine reg IMPORT 'c:\\windows\\temp\\reg_keys64.reg' /reg:64", dotnet)
        self.assertIn("wine reg IMPORT 'c:\\windows\\temp\\reg_keys32.reg' /reg:32", dotnet)
        self.assertIn("mscoreei_old.dll", dotnet)
        self.assertIn("windows/syswow64/mscoree.dll", dotnet)
        self.assertIn("windows/system32/mscoree.dll", dotnet)
        self.assertIn("windows/Microsoft.NET/Framework/v4.0.30319/clr.dll", dotnet)
        self.assertIn("windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll", dotnet)
        self.assertIn("windows/Microsoft.NET/Framework64/v4.0.30319/clrjit.dll", dotnet)
        self.assertNotIn("netfx_Full_x86.msi", dotnet)
        self.assertNotIn("netfx_Full_x64.msi", dotnet)
        self.assertNotIn("wine msiexec /i \"$netfx_msi_win\"", dotnet)
        self.assertNotIn("install_dotnet_msi ", dotnet)
        self.assertNotIn("CAGE_DOTNET48_TIMEOUT", dotnet)
        self.assertNotIn("PowerShell", dotnet)
        self.assertNotIn("choco.exe install", dotnet)

    def test_chocolatey_registry_prep_sets_win10_and_upstream_dll_policy(self):
        registry = _commands_for(_manifest().modules[0].build(), "Prepare Wine registry for Chocolatey")

        self.assertIn("winecfg /v win10", registry)
        self.assertIn("CAGE_WINECFG_TIMEOUT", registry)
        self.assertIn("CAGE_WINE_REG_TIMEOUT", registry)
        self.assertIn("HKCU\\Software\\Wine\\DllOverrides", registry)
        self.assertIn("/v mscoree /t REG_SZ /d native /f", registry)
        self.assertNotIn("/v mscoree /t REG_SZ /d native,builtin /f", registry)
        self.assertIn("HKLM\\Software\\Microsoft\\.NETFramework", registry)
        self.assertIn("/v OnlyUseLatestCLR /t REG_DWORD /d 1 /f", registry)
        self.assertIn("AppDefaults\\pwsh.exe\\DllOverrides", registry)
        self.assertNotIn("AppDefaults\\choco.exe\\DllOverrides", registry)
        self.assertIn('/v amsi /d "" /f', registry)
        self.assertIn('/v dwmapi /d "" /f', registry)
        self.assertIn("/v rpcrt4 /d native,builtin /f", registry)
        self.assertNotIn("AppDefaults\\choco.exe\\DllOverrides' /v mscoree", registry)
        self.assertIn("HKCU\\Environment", registry)
        self.assertIn("/v PS7", registry)
        self.assertIn("C:\\Program Files\\PowerShell\\7\\pwsh.exe", registry)

    def test_chocolatey_native_promotion_replaces_pwsh_finalizer_boundary(self):
        promote = _commands_for(_manifest().modules[0].build(), "Promote Chocolatey natively")

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

    def test_chocolatey_native_promotion_preserves_payload_and_uses_real_choco_in_bin(self):
        promote = _commands_for(_manifest().modules[0].build(), "Promote Chocolatey natively")

        self.assertIn('rm -rf "$canonical_choco_dir"', promote)
        self.assertIn('source = Path(sys.argv[1])', promote)
        self.assertIn('dest = Path(sys.argv[2])', promote)
        self.assertIn('redirects = dest / "redirects"', promote)
        self.assertIn('bin_dir = dest / "bin"', promote)
        self.assertIn('if item.name.lower() == "choco.exe":', promote)
        self.assertIn('continue', promote)
        self.assertIn('shutil.copy2(root_choco, choco)', promote)
        self.assertIn('choco = bin_dir / "choco.exe"', promote)
        self.assertIn('root_choco = dest / "choco.exe"', promote)
        self.assertIn('if not root_choco.is_file():', promote)
        self.assertIn('if choco.stat().st_size != root_choco.stat().st_size:', promote)
        self.assertLess(promote.index('root_choco = dest / "choco.exe"'), promote.index('shutil.copy2(root_choco, choco)'))
        self.assertIn('native_loader_mscoree="$wine_prefix/drive_c/windows/system32/mscoree.dll"', promote)
        self.assertIn('native_loader_mscoreei="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/mscoreei.dll"', promote)
        self.assertIn('native_loader_clr="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"', promote)
        self.assertIn('native_loader_clrjit="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clrjit.dll"', promote)
        self.assertIn('native_loader_ucrtbase="$wine_prefix/drive_c/windows/system32/ucrtbase_clr0400.dll"', promote)
        self.assertIn('native_loader_vcruntime="$wine_prefix/drive_c/windows/system32/vcruntime140_clr0400.dll"', promote)
        self.assertIn('cp -f "$native_loader_mscoree" "$canonical_bin_dir/mscoree.dll"', promote)
        self.assertIn('cp -f "$native_loader_mscoreei" "$canonical_bin_dir/mscoreei.dll"', promote)
        self.assertIn('cp -f "$native_loader_clr" "$canonical_bin_dir/clr.dll"', promote)
        self.assertIn('cp -f "$native_loader_clrjit" "$canonical_bin_dir/clrjit.dll"', promote)
        self.assertIn('cp -f "$native_loader_ucrtbase" "$canonical_bin_dir/ucrtbase_clr0400.dll"', promote)
        self.assertIn('cp -f "$native_loader_vcruntime" "$canonical_bin_dir/vcruntime140_clr0400.dll"', promote)
        self.assertIn("helpers", promote)
        self.assertIn("tools", promote)
        self.assertIn("redirects", promote)

    def test_chocolatey_native_promotion_sets_environment_without_pwsh(self):
        promote = _commands_for(_manifest().modules[0].build(), "Promote Chocolatey natively")

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
        steps = _manifest().modules[0].build()
        promote = _commands_for(steps, "Promote Chocolatey natively")
        diagnostic = _commands_for(steps, "Diagnose Chocolatey readiness")

        self.assertIn("ProgramData/tools/ChocolateyInstall/choco.exe", promote)
        self.assertIn("ProgramData/chocolatey/bin/choco.exe", promote)
        self.assertIn("raw ChocolateyInstall payload is only a source", promote)
        self.assertIn("ERROR: native Chocolatey promotion did not create canonical choco.exe", promote)
        self.assertNotIn("CAGE_CHOCOLATEY_VERIFY_TIMEOUT", promote)
        self.assertNotIn("choco --version", promote)
        self.assertIn("CAGE_CHOCOLATEY_VERIFY_TIMEOUT", diagnostic)
        self.assertIn("choco_exe_win='C:\\ProgramData\\chocolatey\\bin\\choco.exe'", diagnostic)
        self.assertIn('timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-20s}" wine "$choco_exe_win" --version', diagnostic)
        self.assertNotIn('timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" --version', diagnostic)
        self.assertIn("export ChocolateyInstall=", promote)
        self.assertIn("export ChocolateyToolsLocation=", promote)
        self.assertIn("unset WINEDLLOVERRIDES", promote)
        self.assertNotIn("mscoree=n,b", promote)
        self.assertNotIn("mscoree=n'", promote)
        self.assertNotIn("logs/chocolatey-verify.log", promote)
        self.assertNotIn("Continuing to diagnostic step", promote)
        self.assertNotIn("Chocolatey-for-wine finalizer did not create canonical choco.exe", promote)
        self.assertNotIn("CAGE_CHOCOLATEY_FINALIZE_TIMEOUT", promote)

    def test_chocolatey_package_install_uses_canonical_choco_only(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        policy = _commands_for(steps, "Apply Chocolatey feature policy")
        package = _commands_for(steps, "Install Chocolatey packages: 7zip notepadplusplus")

        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("CAGE_CHOCOLATEY_INSTALL_TIMEOUT", package)
        self.assertIn("feature disable --name=powershellHost", policy)
        self.assertNotIn("feature enable -n allowGlobalConfirmation", policy)
        self.assertIn("disable-powershellHost.log", policy)
        self.assertIn("feature-list.log", policy)
        self.assertIn("wine \"$choco_exe_win\" install 7zip notepadplusplus -y", package)
        self.assertNotIn("wine \"$choco_exe\" install", package)
        self.assertIn("choco_diag_status", package)
        self.assertIn("policy_status", package)
        self.assertIn("export ChocolateyInstall=", package)
        self.assertIn("export ChocolateyToolsLocation=", package)
        self.assertIn("unset WINEDLLOVERRIDES", package)
        self.assertNotIn("mscoree=n,b", package)
        self.assertNotIn("mscoree=n'", package)

    def test_chocolatey_diagnostic_writes_json_before_package_install(self):
        steps = _manifest(["7zip"]).modules[0].build()
        diagnostic = _commands_for(steps, "Diagnose Chocolatey readiness")
        package = _commands_for(steps, "Install Chocolatey packages: 7zip")

        self.assertIn("metadata/chocolatey-diagnostic.json", diagnostic)
        self.assertIn("cage.chocolatey-diagnostic/v0", diagnostic)
        self.assertIn("canonicalChocoExists", diagnostic)
        self.assertIn("rawToolsPayloadExists", diagnostic)
        self.assertIn("winepathCanonical", diagnostic)
        self.assertIn("registryEnvironment", diagnostic)
        self.assertIn("wineDllOverridesMscoree", diagnostic)
        self.assertIn("wineDllOverridesMscoreeNative", diagnostic)
        self.assertNotIn("wineDllOverridesMscoreeNativeBuiltin", diagnostic)
        self.assertIn("dotnetReleaseRegistry", diagnostic)
        self.assertIn("nativeMscoreeExists", diagnostic)
        self.assertIn("nativeMscoreeiExists", diagnostic)
        self.assertIn("nativeClrExists", diagnostic)
        self.assertIn("nativeClrjitExists", diagnostic)
        self.assertIn("nativeWow64MscoreeExists", diagnostic)
        self.assertIn("nativeWow64MscoreeiExists", diagnostic)
        self.assertIn("nativeWow64ClrExists", diagnostic)
        self.assertIn("nativeUcrtbaseClrExists", diagnostic)
        self.assertIn("nativeVcruntimeClrExists", diagnostic)
        self.assertIn("appLocalMscoreeExists", diagnostic)
        self.assertIn("appLocalMscoreeiExists", diagnostic)
        self.assertIn("appLocalClrExists", diagnostic)
        self.assertIn("appLocalClrjitExists", diagnostic)
        self.assertIn("appLocalUcrtbaseClrExists", diagnostic)
        self.assertIn("appLocalVcruntimeClrExists", diagnostic)
        self.assertIn("fileSizes", diagnostic)
        self.assertIn("canonicalChoco", diagnostic)
        self.assertIn("chocoVersion", diagnostic)
        self.assertIn("wineCmdEcho", diagnostic)
        self.assertIn("chocoVersionViaCmd", diagnostic)
        self.assertIn("choco-version-winedebug.log", diagnostic)
        self.assertIn("choco-mscoree-loader.log", diagnostic)
        self.assertIn("choco_exe_win='C:\\ProgramData\\chocolatey\\bin\\choco.exe'", diagnostic)
        self.assertIn('wine "$choco_exe_win" --version', diagnostic)
        self.assertIn('WINEDEBUG=+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-15s}" wine "$choco_exe_win" --version', diagnostic)
        self.assertNotIn('WINEDEBUG=+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe" --version', diagnostic)
        self.assertIn("sourceList", diagnostic)
        self.assertIn("export ChocolateyInstall=", diagnostic)
        self.assertIn("export ChocolateyToolsLocation=", diagnostic)
        self.assertIn("unset WINEDLLOVERRIDES", diagnostic)
        self.assertNotIn("mscoree=n,b", diagnostic)
        self.assertNotIn("mscoree=n'", diagnostic)
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
