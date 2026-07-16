"""Chocolatey prepared-runtime module tests."""
from __future__ import annotations

import unittest

from core.manifest import Manifest


_RUNTIME = {
    "id": "cfw-runtime-test",
    "url": "https://example.invalid/cfw-runtime-prefix.tar.gz",
    "sha256": "a" * 64,
    "evidenceUrl": "https://example.invalid/runtime.json",
    "evidenceSha256": "b" * 64,
    "wineVersions": ["wine-9.0"],
}


def _manifest(packages=None, *, include_runtime=True, **module_overrides):
    install = {"packages": packages or ["7zip"]}
    if include_runtime:
        install["runtimeArtifact"] = dict(_RUNTIME)
    module = {"type": "chocolatey", "install": install}
    module.update(module_overrides)
    return Manifest.from_dict({
        "schemaVersion": "cage.app/v0",
        "name": "test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "9.0"},
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

    def test_chocolatey_module_preserves_package_intent_and_provenance(self):
        manifest = _manifest(["7zip", "notepadplusplus"])
        manifest.provenance = {"test": "value"}
        self.assertEqual(manifest.modules[0].install["packages"], ["7zip", "notepadplusplus"])
        self.assertEqual(manifest.provenance, {"test": "value"})

    def test_chocolatey_claims_prepared_runtime_capabilities(self):
        capabilities = _manifest().modules[0].capabilities()
        self.assertEqual(capabilities, {
            "package-manager": "chocolatey-2.6.0",
            "package-execution-host": "external-windows-powershell",
            "prefix-foundation": "cfw-chocolatey-runtime",
        })
        self.assertNotIn("engine", capabilities)
        self.assertNotIn("winps-shim", capabilities)

    def test_chocolatey_builds_one_prefix_seed_boundary(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        descriptions = [step.description for step in steps]
        script = _all_commands(steps)
        self.assertEqual(descriptions, [
            "Record CFW prepared runtime profile",
            "Seed CFW prepared prefix",
            "Diagnose Chocolatey readiness",
            "Verify Chocolatey external-host policy",
            "Prove Chocolatey local package lifecycle",
            "Install Chocolatey packages: 7zip notepadplusplus",
        ])
        seed = next(step for step in steps if step.description == "Seed CFW prepared prefix")
        self.assertEqual(seed.kind, "prefix-seed")
        self.assertIn(_RUNTIME["url"], script)
        self.assertIn(_RUNTIME["sha256"], script)
        self.assertIn(_RUNTIME["evidenceUrl"], script)
        self.assertIn("tar -xzf", script)
        self.assertIn("cfw-chocolatey-runtime", script)
        self.assertNotIn("KB3AIK_EN.iso", script)
        self.assertNotIn("Win7AndW2K8R2-KB3191566-x64.zip", script)
        self.assertNotIn("PowerShell-7.5.5-win-x64.msi", script)
        self.assertNotIn("Install Synchro PowerShell layer", descriptions)
        self.assertNotIn("Install Windows PowerShell 5.1 backend", descriptions)

    def test_runtime_artifact_is_strictly_verified(self):
        steps = _manifest().modules[0].build()
        seed = _commands_for(steps, "Seed CFW prepared prefix")
        self.assertIn("cage_fetch_verified", seed)
        self.assertIn("sha256sum", seed)
        self.assertIn("runtime evidence status is not passed", seed)
        self.assertIn("unexpected CFW runtime provider", seed)
        self.assertIn("does not declare compatibility", seed)
        self.assertIn("synchroX64", seed)
        self.assertIn("synchroX86", seed)
        self.assertIn(".cage-prefix-seeded", seed)

    def test_missing_released_runtime_fails_clearly(self):
        manifest = _manifest(include_runtime=False)
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("no released CFW runtime is pinned yet", str(ctx.exception))

    def test_runtime_artifact_rejects_incomplete_hash(self):
        manifest = _manifest()
        manifest.modules[0].install["runtimeArtifact"]["sha256"] = "abc"
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("complete lowercase sha256", str(ctx.exception))

    def test_package_install_uses_canonical_choco_and_disabled_internal_host(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        package = _commands_for(steps, "Install Chocolatey packages: 7zip notepadplusplus")
        policy = _commands_for(steps, "Verify Chocolatey external-host policy")
        self.assertIn("ProgramData/chocolatey/bin/choco.exe", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("wine \"$choco_exe_win\" install 7zip notepadplusplus -y", package)
        self.assertIn("policy_status", package)
        self.assertIn("feature disable --name=powershellHost", policy)
        self.assertIn("powershellHost\\|(disabled|false)", policy)

    def test_chocolatey_diagnostic_precedes_package_install(self):
        steps = _manifest(["7zip"]).modules[0].build()
        diagnostic = _commands_for(steps, "Diagnose Chocolatey readiness")
        package = _commands_for(steps, "Install Chocolatey packages: 7zip")
        self.assertIn("metadata/chocolatey-diagnostic.json", diagnostic)
        self.assertIn("canonicalChocoExists", diagnostic)
        self.assertIn("chocoVersion", diagnostic)
        self.assertIn("sourceList", diagnostic)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", diagnostic)
        self.assertIn("choco_diag_status", package)

    def test_chocolatey_rejects_shell_like_package_names(self):
        manifest = _manifest(["7zip; rm -rf /"])
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("must use letters, numbers", str(ctx.exception))

    def test_chocolatey_rejects_non_string_package_names(self):
        manifest = _manifest(["7zip", 42])
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("install.packages", str(ctx.exception))

    def test_chocolatey_accepts_custom_source_url(self):
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
