"""Chocolatey module tests for upstream Chocolatey-for-wine integration."""
from __future__ import annotations

import unittest
from typing import Any

from core.manifest import Manifest


def _manifest(packages: list[Any] | None = None, **module_overrides):
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

    def test_chocolatey_module_claims_upstream_capability_slots(self):
        capabilities = _manifest().modules[0].capabilities()

        self.assertEqual(capabilities["engine"], "chocolatey-for-wine-upstream")
        self.assertEqual(capabilities["winps-shim"], "chocolatey-for-wine-upstream")
        self.assertEqual(capabilities["shim-library"], "chocolatey-for-wine")

    def test_chocolatey_module_rejects_shell_like_package_names(self):
        manifest = _manifest(["7zip; rm -rf /"])

        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()

        self.assertIn("must use letters, numbers", str(ctx.exception))

    def test_chocolatey_module_rejects_non_string_package_names(self):
        manifest = _manifest(["7zip", 42])

        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()

        self.assertIn("install.packages", str(ctx.exception))

    def test_chocolatey_module_accepts_custom_source_url(self):
        manifest = _manifest(source="https://custom.choco.source/")

        self.assertEqual(manifest.modules[0].source, "https://custom.choco.source/")
        script = _all_commands(manifest.modules[0].build())
        self.assertIn(" -s 'https://custom.choco.source/'", script)

    def test_chocolatey_builds_upstream_installer_then_diagnostics_then_packages(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        descriptions = [step.description for step in steps]
        script = _all_commands(steps)

        self.assertEqual(descriptions, [
            "Install Chocolatey-for-wine via upstream ChoCinstaller",
            "Diagnose Chocolatey readiness",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        self.assertIn("Running upstream Chocolatey-for-wine installer", script)
        self.assertIn("ChoCinstaller", script)
        self.assertIn('wine "$cfw_installer" /s /q', script)
        self.assertNotIn("Install PowerShell 7 MSI for Chocolatey", script)
        self.assertNotIn("Install .NET Framework 4.8 from dedicated MSI step", script)
        self.assertNotIn("Promote Chocolatey natively", script)
        self.assertNotIn("zipfile.ZipFile", script)
        self.assertNotIn("community.chocolatey.org/api/v2/package/chocolatey", script)

    def test_chocolatey_upstream_installer_downloads_and_extracts_pinned_release(self):
        upstream = "\n".join(_manifest().modules[0].build()[0].commands)

        self.assertIn("https://github.com/PietJankbal/Chocolatey-for-wine/releases/download/v0.5c.755/Chocolatey-for-wine.7z", upstream)
        self.assertIn("87f4ecc08a9b22f16aa5633ca107c151ddf3fed0b256fed9fb99680af7095d14", upstream)
        self.assertIn("actual_cfw_archive_sha", upstream)
        self.assertIn("extract_7z_archive", upstream)
        self.assertIn('cfw_installer="$(find "$cfw_extract" -maxdepth 1 -type f -name', upstream)
        self.assertIn("ChoCinstaller_*.exe", upstream)
        self.assertIn("CAGE_CHOCOLATEY_UPSTREAM_TIMEOUT", upstream)
        self.assertIn("chocolatey-upstream-installer.log", upstream)
        self.assertIn("installer_rc", upstream)
        self.assertIn("CFW_CACHE", upstream)
        self.assertIn("/s /q", upstream)

    def test_chocolatey_upstream_installer_verifies_canonical_choco_without_manual_promotion(self):
        upstream = "\n".join(_manifest().modules[0].build()[0].commands)

        self.assertIn("ProgramData/chocolatey/bin/choco.exe", upstream)
        self.assertIn("CAGE_CHOCOLATEY_VERIFY_TIMEOUT", upstream)
        self.assertIn('timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" --version', upstream)
        self.assertIn("ChocolateyInstall", upstream)
        self.assertIn("ChocolateyToolsLocation", upstream)
        self.assertIn("mscoree=n", upstream)
        self.assertIn("Continuing to diagnostic step", upstream)
        self.assertNotIn("raw_choco_dir", upstream)
        self.assertNotIn("shutil.copytree", upstream)
        self.assertNotIn("ProgramData/tools/ChocolateyInstall", upstream)

    def test_chocolatey_diagnostic_writes_json_before_package_install(self):
        steps = _manifest(["7zip"]).modules[0].build()
        diagnostic = "\n".join(steps[1].commands)
        package = "\n".join(steps[2].commands)

        self.assertIn("metadata/chocolatey-diagnostic.json", diagnostic)
        self.assertIn("cage.chocolatey-diagnostic/v0", diagnostic)
        self.assertIn("upstreamInstaller", diagnostic)
        self.assertIn("canonicalChocoExists", diagnostic)
        self.assertIn("winepathCanonical", diagnostic)
        self.assertIn("registryEnvironment", diagnostic)
        self.assertIn("wineDllOverridesMscoree", diagnostic)
        self.assertIn("dotnetReleaseRegistry", diagnostic)
        self.assertIn("nativeMscoreeExists", diagnostic)
        self.assertIn("nativeMscoreeiExists", diagnostic)
        self.assertIn("nativeClrExists", diagnostic)
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

    def test_chocolatey_package_install_uses_canonical_choco_only(self):
        package = "\n".join(_manifest(["7zip", "notepadplusplus"]).modules[0].build()[2].commands)

        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("CAGE_CHOCOLATEY_INSTALL_TIMEOUT", package)
        self.assertIn("wine \"$choco_exe\" install 7zip notepadplusplus -y", package)
        self.assertIn("choco_diag_status", package)
        self.assertIn("export ChocolateyInstall=", package)
        self.assertIn("export ChocolateyToolsLocation=", package)
        self.assertIn("mscoree=n", package)
        self.assertNotIn("unset WINEDLLOVERRIDES", package)

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
