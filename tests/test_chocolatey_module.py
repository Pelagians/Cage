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
            "Bootstrap Chocolatey-for-Wine fork",
            "Diagnose Chocolatey readiness",
            "Apply Chocolatey feature policy",
            "Prove Chocolatey local package lifecycle",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        self.assertIn("Bootstrap pinned Chocolatey-for-Wine fork", script)
        self.assertIn("ChoCinstaller_", script)
        self.assertIn("canonical choco.exe", script)
        self.assertNotIn("Install native .NET loader", script)
        self.assertNotIn("Install frozen dotnet481 profile", script)
        self.assertNotIn("Promote Chocolatey natively", script)
        self.assertLess(descriptions.index("Bootstrap Chocolatey-for-Wine fork"), descriptions.index("Diagnose Chocolatey readiness"))
        self.assertLess(descriptions.index("Diagnose Chocolatey readiness"), descriptions.index("Apply Chocolatey feature policy"))
        self.assertLess(descriptions.index("Apply Chocolatey feature policy"), descriptions.index("Prove Chocolatey local package lifecycle"))
        self.assertLess(descriptions.index("Prove Chocolatey local package lifecycle"), descriptions.index("Install Chocolatey packages: 7zip notepadplusplus"))



    def test_fork_bootstrap_uses_private_verified_workdir_and_strict_success_boundary(self):
        bootstrap = _commands_for(_manifest().modules[0].build(), "Bootstrap Chocolatey-for-Wine fork")

        self.assertIn('cfw_work="$wine_prefix/.cage/chocolatey-bootstrap/cfw-v0.5c.755-noah.5-choco-2.6.0-fork-r11"', bootstrap)
        self.assertIn('rm -rf "$cfw_work"', bootstrap)
        self.assertIn('cfw_payload_cache="$cfw_work/choc_install_files"', bootstrap)
        self.assertIn('cfw_installer="$cfw_extract/ChoCinstaller_0.5c.755.exe"', bootstrap)
        self.assertIn('2>&1 | tee "$logs_dir/installer.log"', bootstrap)
        self.assertIn("grep -a --line-buffered '^\\[cfw\\] stage='", bootstrap)
        self.assertIn('installer_rc="${PIPESTATUS[0]}"', bootstrap)
        self.assertIn('chocolatey-path-inventory.log', bootstrap)
        self.assertIn('rawRoot', bootstrap)
        self.assertIn('canonicalRoot', bootstrap)
        self.assertIn('canonicalRedirect', bootstrap)
        self.assertIn('canonicalBin', bootstrap)
        self.assertIn('nestedRoot', bootstrap)
        self.assertIn('discoveredChoco', bootstrap)
        self.assertIn("path.name.lower() == 'choco.exe'", bootstrap)
        self.assertIn('wine "$cfw_installer_win" /s /q', bootstrap)
        self.assertIn('export CFW_CACHE="$cfw_cache_win"', bootstrap)
        self.assertIn('export CFW_OFFLINE=1', bootstrap)
        self.assertIn('installer_rc == 0 and settle_rc == 0 and canonical_rc == 0', bootstrap)
        self.assertIn('[ "$installer_rc" -ne 0 ] || [ "$settle_rc" -ne 0 ] || [ "$canonical_rc" -ne 0 ]', bootstrap)
        self.assertIn('ProgramData/chocolatey/bin/choco.exe', bootstrap)
        self.assertIn('Chocolatey-for-Wine bootstrap failed', bootstrap)
        for payload in (
            "chocolatey.2.6.0.nupkg",
            "PowerShell-7.5.5-win-x64.msi",
            "ndp48-x86-x64-allos-enu.exe",
            "windows6.1-kb958488-v6001-x64_a137e4f328f01146dfa75d7b5a576090dee948dc.msu",
            "d3dcompiler_47.dll",
            "d3dcompiler_47_32.dll",
            "ConEmuPack.230724.7z",
            "sevenzipextractor.1.0.19.nupkg",
            "windowsserver2003-kb968930-x64-eng_8ba702aa016e4c5aed581814647f4d55635eff5c.exe",
        ):
            self.assertIn(payload, bootstrap)







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
        self.assertIn("chocoVersion", diagnostic)
        self.assertIn("sourceList", diagnostic)
        self.assertIn("chocoVersionViaCmd", diagnostic)
        self.assertIn('wine "$choco_exe_win" --version', diagnostic)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", diagnostic)
        self.assertNotIn("appLocalMscoreeExists", diagnostic)
        self.assertNotIn("rawToolsPayloadExists", diagnostic)
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
