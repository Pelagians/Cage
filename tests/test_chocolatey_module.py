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

    def test_chocolatey_module_claims_layered_capabilities(self):
        capabilities = _manifest().modules[0].capabilities()

        self.assertEqual(capabilities["engine"], "windows-powershell-5.1-cfw")
        self.assertEqual(capabilities["winps-shim"], "synchro-v4.2.0")
        self.assertEqual(capabilities["package-manager"], "chocolatey-2.6.0")
        self.assertEqual(capabilities["compatibility-pack"], "chocolatey-for-wine-v1")

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

    def test_chocolatey_builds_explicit_layers_in_order(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        descriptions = [step.description for step in steps]
        script = _all_commands(steps)

        self.assertEqual(descriptions, [
            "Record layered Chocolatey bootstrap profile",
            "Bootstrap CFW prerequisites and Chocolatey",
            "Install Windows PowerShell 5.1 backend",
            "Install Synchro PowerShell layer (v4.2.0)",
            "Install CFW compatibility profile fragments",
            "Prove composed PowerShell compatibility layer",
            "Diagnose Chocolatey readiness",
            "Apply Chocolatey feature policy",
            "Prove Chocolatey local package lifecycle",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        self.assertIn("Bootstrap pinned Chocolatey-for-Wine fork", script)
        self.assertIn("ChoCinstaller_", script)
        self.assertIn("windows-powershell-5.1-cfw", script)
        self.assertIn("Win7AndW2K8R2-KB3191566-x64.zip", script)
        self.assertIn("f383c34aa65332662a17d95409a2ddedadceda74427e35d05024cd0a6a2fa647", script)
        self.assertIn("PWSH_PATH", script)
        self.assertIn("ps51.exe", script)
        self.assertIn("synchro-v4.2.0", script)
        self.assertIn("10-synchro.ps1", script)
        self.assertIn("20-chocolatey.ps1", script)
        self.assertIn("30-cfw-winetricks.ps1", script)
        self.assertIn("40-cfw-command-adapters.ps1", script)
        self.assertIn("c3b4923d0f63188843bd2a15be64bca8f4a9902b", script)
        self.assertIn("composed-powershell-layer-ok", script)
        self.assertLess(
            descriptions.index("Bootstrap CFW prerequisites and Chocolatey"),
            descriptions.index("Install Windows PowerShell 5.1 backend"),
        )
        self.assertLess(
            descriptions.index("Install Windows PowerShell 5.1 backend"),
            descriptions.index("Install Synchro PowerShell layer (v4.2.0)"),
        )
        self.assertLess(
            descriptions.index("Install Synchro PowerShell layer (v4.2.0)"),
            descriptions.index("Install CFW compatibility profile fragments"),
        )
        self.assertLess(
            descriptions.index("Prove composed PowerShell compatibility layer"),
            descriptions.index("Diagnose Chocolatey readiness"),
        )
        self.assertLess(
            descriptions.index("Prove Chocolatey local package lifecycle"),
            descriptions.index("Install Chocolatey packages: 7zip notepadplusplus"),
        )

    def test_fork_bootstrap_is_transitional_and_strict(self):
        steps = _manifest().modules[0].build()
        bootstrap_step = next(step for step in steps if step.description == "Bootstrap CFW prerequisites and Chocolatey")
        bootstrap = "\n".join(bootstrap_step.commands)

        self.assertEqual(bootstrap_step.timeout, 4200)
        self.assertTrue(bootstrap_step.metadata["transitionalBootstrap"])
        self.assertIn("cfw-v0.5c.755-noah.6-choco-2.6.0-synchro-r13", bootstrap)
        self.assertIn('cfw_payload_cache="$cfw_work/choc_install_files"', bootstrap)
        self.assertIn('cfw_installer="$cfw_extract/ChoCinstaller_0.5c.755.exe"', bootstrap)
        self.assertIn('wine "$cfw_installer_win" /s /q', bootstrap)
        self.assertIn('export CFW_OFFLINE=1', bootstrap)
        self.assertIn('export CFW_CONTAINER_BUILDER=1', bootstrap)
        self.assertIn('ProgramData/chocolatey/bin/choco.exe', bootstrap)
        self.assertIn('Chocolatey-for-Wine bootstrap failed', bootstrap)
        self.assertIn("PowerShell-7.5.5-win-x64.msi", bootstrap)

        descriptions = [step.description for step in steps]
        bootstrap_index = descriptions.index("Bootstrap CFW prerequisites and Chocolatey")
        engine_index = descriptions.index("Install Windows PowerShell 5.1 backend")
        self.assertGreater(engine_index, bootstrap_index)

    def test_windows_powershell_backend_is_verified_and_does_not_use_native_expand(self):
        steps = _manifest().modules[0].build()
        engine = _commands_for(steps, "Install Windows PowerShell 5.1 backend")

        self.assertIn("Win7AndW2K8R2-KB3191566-x64.zip", engine)
        self.assertIn("wmf-cab-extract.log", engine)
        self.assertIn('7z x -y "$cab"', engine)
        self.assertNotIn("system32/expnd/expand.exe", engine)
        self.assertIn("engine-version=", engine)
        self.assertIn("fileSentinel", engine)
        self.assertIn("wineserverSettle", engine)

    def test_profile_fragment_install_requires_cage_loader_and_synchro(self):
        steps = _manifest().modules[0].build()
        profile = _commands_for(steps, "Install CFW compatibility profile fragments")
        verify = _commands_for(steps, "Prove composed PowerShell compatibility layer")

        self.assertIn('profile_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"', profile)
        self.assertIn('fragment_dir="$profile_root/profile.d"', profile)
        self.assertIn('test -s "$profile64"', profile)
        self.assertIn('test -s "$profile32"', profile)
        self.assertIn('test -s "$synchro_fragment"', profile)
        self.assertIn("powershell-profile-composition.json", profile)
        self.assertIn("windows-powershell-5.1-cfw", profile)
        self.assertIn("Update-SessionEnvironment", verify)
        self.assertIn("Get-Alias -Name winetricks", verify)
        self.assertIn("exit 37", verify)
        self.assertIn("powershell-layer.json", verify)
        self.assertIn("ps51.exe", verify)

    def test_chocolatey_package_install_uses_canonical_choco_only(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        policy = _commands_for(steps, "Apply Chocolatey feature policy")
        package = _commands_for(steps, "Install Chocolatey packages: 7zip notepadplusplus")

        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("CAGE_CHOCOLATEY_INSTALL_TIMEOUT", package)
        self.assertIn("feature disable --name=powershellHost", policy)
        self.assertNotIn("feature enable -n allowGlobalConfirmation", policy)
        self.assertIn("wine \"$choco_exe_win\" install 7zip notepadplusplus -y", package)
        self.assertIn("choco_diag_status", package)
        self.assertIn("policy_status", package)
        self.assertIn("export ChocolateyInstall=", package)
        self.assertIn("export ChocolateyToolsLocation=", package)
        self.assertIn("unset WINEDLLOVERRIDES", package)

    def test_chocolatey_diagnostic_writes_json_before_package_install(self):
        steps = _manifest(["7zip"]).modules[0].build()
        diagnostic = _commands_for(steps, "Diagnose Chocolatey readiness")
        package = _commands_for(steps, "Install Chocolatey packages: 7zip")

        self.assertIn("metadata/chocolatey-diagnostic.json", diagnostic)
        self.assertIn("cage.chocolatey-diagnostic/v0", diagnostic)
        self.assertIn("canonicalChocoExists", diagnostic)
        self.assertIn("chocoVersion", diagnostic)
        self.assertIn("sourceList", diagnostic)
        self.assertIn('wine "$choco_exe_win" --version', diagnostic)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", diagnostic)
        self.assertLess(
            _all_commands(steps).index("Diagnose Chocolatey readiness"),
            _all_commands(steps).index("Install Chocolatey packages"),
        )
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
