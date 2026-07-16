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
        self.assertEqual(manifest.modules[0].install["packages"], ["7zip", "notepadplusplus"])
        self.assertEqual(manifest.provenance, {"test": "value"})

    def test_chocolatey_module_claims_integrated_runtime_capabilities(self):
        capabilities = _manifest().modules[0].capabilities()
        self.assertEqual(capabilities, {
            "package-manager": "chocolatey-2.6.0",
            "package-execution-host": "chocolatey-in-process-powershell",
            "compatibility-runtime": "cfw-integrated-chocolatey-runtime",
        })
        self.assertNotIn("engine", capabilities)
        self.assertNotIn("winps-shim", capabilities)

    def test_chocolatey_builds_one_cfw_runtime_boundary(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        descriptions = [step.description for step in steps]
        script = _all_commands(steps)
        self.assertEqual(descriptions, [
            "Record CFW integrated runtime profile",
            "Bootstrap CFW prerequisites and canonical Chocolatey",
            "Finalize CFW integrated Chocolatey runtime",
            "Diagnose Chocolatey readiness",
            "Prove Chocolatey local package lifecycle",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        self.assertIn("cfw-integrated-chocolatey-runtime", script)
        self.assertIn("compat/container-runtime.sh", script)
        self.assertIn("CFW_PAYLOAD_CACHE_POSIX", script)
        self.assertIn("cfw-runtime/container-runtime.json", script)
        self.assertNotIn("KB3AIK_EN.iso", script)
        self.assertNotIn("Win7AndW2K8R2-KB3191566-x64.zip", script)
        self.assertNotIn("Install Synchro PowerShell layer", descriptions)
        self.assertNotIn("Install Windows PowerShell 5.1 backend", descriptions)

    def test_fork_bootstrap_is_strict_and_precedes_runtime_finalization(self):
        steps = _manifest().modules[0].build()
        bootstrap_step = next(
            step for step in steps
            if step.description == "Bootstrap CFW prerequisites and canonical Chocolatey"
        )
        finalizer_step = next(
            step for step in steps
            if step.description == "Finalize CFW integrated Chocolatey runtime"
        )
        bootstrap = "\n".join(bootstrap_step.commands)
        finalizer = "\n".join(finalizer_step.commands)
        self.assertEqual(bootstrap_step.timeout, 4200)
        self.assertIn("ChoCinstaller_0.5c.755.exe", bootstrap)
        self.assertIn("export CFW_OFFLINE=1", bootstrap)
        self.assertIn("export CFW_CONTAINER_BUILDER=1", bootstrap)
        self.assertIn("ProgramData/chocolatey/bin/choco.exe", bootstrap)
        self.assertIn("cage_fetch_verified", finalizer)
        self.assertIn("CFW_CONTAINER_RUNTIME_SHA256", finalizer)
        self.assertIn("powershellHostEnabled", finalizer)
        self.assertIn("chocolatey-feature-policy.json", finalizer)
        self.assertLess(steps.index(bootstrap_step), steps.index(finalizer_step))

    def test_package_install_uses_canonical_choco_and_cfw_policy_evidence(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        package = _commands_for(steps, "Install Chocolatey packages: 7zip notepadplusplus")
        finalizer = _commands_for(steps, "Finalize CFW integrated Chocolatey runtime")
        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("wine \"$choco_exe_win\" install 7zip notepadplusplus -y", package)
        self.assertIn("policy_status", package)
        self.assertIn("owner\": \"cfw", finalizer)
        self.assertIn("powershellHost\": \"enabled", finalizer)

    def test_chocolatey_diagnostic_writes_json_before_package_install(self):
        steps = _manifest(["7zip"]).modules[0].build()
        diagnostic = _commands_for(steps, "Diagnose Chocolatey readiness")
        package = _commands_for(steps, "Install Chocolatey packages: 7zip")
        self.assertIn("metadata/chocolatey-diagnostic.json", diagnostic)
        self.assertIn("canonicalChocoExists", diagnostic)
        self.assertIn("chocoVersion", diagnostic)
        self.assertIn("sourceList", diagnostic)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", diagnostic)
        self.assertLess(
            _all_commands(steps).index("Diagnose Chocolatey readiness"),
            _all_commands(steps).index("Install Chocolatey packages"),
        )
        self.assertIn("choco_diag_status", package)

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
        script = _all_commands(manifest.modules[0].build())
        self.assertIn(" -s 'https://custom.choco.source/'", script)

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
