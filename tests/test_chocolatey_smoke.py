"""Chocolatey local package lifecycle and diagnostic contracts."""
from __future__ import annotations

import io
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.chocolatey.assets import asset_sha256, load_asset, load_asset_bytes
from core.manifest import Manifest, load_manifest

ROOT = Path(__file__).resolve().parents[1]
SMOKE_NUPKG = "cage-chocolatey-smoke.0.1.0.nupkg"
RUNTIME = {
    "id": "cfw-runtime-test",
    "url": "https://example.invalid/cfw-runtime-prefix.tar.gz",
    "evidenceUrl": "https://example.invalid/runtime.json",
    "manifestUrl": "https://example.invalid/cfw-runtime-manifest.json",
    "manifestSha256": "c" * 64,
    "wineImage": "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64,
    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
}


def _steps():
    manifest = Manifest.from_dict({
        "schemaVersion": "cage.app/v0",
        "name": "smoke-test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "11.0"},
        "modules": [{
            "type": "chocolatey",
            "install": {"packages": ["7zip"], "runtimeArtifact": dict(RUNTIME)},
        }],
        "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
    })
    return manifest.modules[0].build()


class ChocolateySmokePackageTests(unittest.TestCase):
    def test_packaged_smoke_nupkg_matches_committed_source(self):
        package = load_asset_bytes(SMOKE_NUPKG)
        self.assertRegex(asset_sha256(SMOKE_NUPKG), r"^[0-9a-f]{64}$")
        expected_members = {
            "cage-chocolatey-smoke.nuspec",
            "tools/chocolateyInstall.ps1",
            "tools/chocolateyUninstall.ps1",
        }
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            names = set(archive.namelist())
            self.assertEqual(names, expected_members)
            archived = {name: archive.read(name) for name in expected_members}

        fixture_root = ROOT / "tests/fixtures/chocolatey-feed"
        fixture_source = fixture_root / "source"
        source_members = {
            "cage-chocolatey-smoke.nuspec": fixture_source / "cage-chocolatey-smoke.nuspec",
            "tools/chocolateyInstall.ps1": fixture_source / "tools/chocolateyInstall.ps1",
            "tools/chocolateyUninstall.ps1": fixture_source / "tools/chocolateyUninstall.ps1",
        }
        for name, source in source_members.items():
            with self.subTest(name=name):
                self.assertEqual(archived[name], source.read_bytes())

        fixture_package = fixture_root / SMOKE_NUPKG
        self.assertEqual(package, fixture_package.read_bytes())
        builder = runpy.run_path(str(fixture_root / "build_smoke_package.py"))
        with tempfile.TemporaryDirectory() as temporary:
            rebuilt = Path(temporary) / SMOKE_NUPKG
            builder["build"](rebuilt)
            self.assertEqual(package, rebuilt.read_bytes())

        install = archived["tools/chocolateyInstall.ps1"].decode("utf-8")
        uninstall = archived["tools/chocolateyUninstall.ps1"].decode("utf-8")
        self.assertIn("chocolateyInstaller.psm1", install)
        self.assertIn("Get-ToolsLocation", install)
        self.assertIn("chocolatey-smoke.sentinel", install)
        self.assertIn("CAGE_CHOCOLATEY_SMOKE", install)
        self.assertIn("PSVersion", install)
        self.assertIn("ProcessPath", install)
        self.assertIn("Is64BitProcess", install)
        self.assertIn("CAGE_CHOCOLATEY_SMOKE_RUN_ID", install)
        self.assertIn("RunId", install)
        self.assertIn("Remove-Item", uninstall)
        self.assertIn("uninstall-proof", uninstall)
        self.assertIn("RunId", uninstall)

    def test_built_wheel_contains_smoke_nupkg(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            source_copy = temporary_path / "source"
            shutil.copytree(
                ROOT,
                source_copy,
                ignore=shutil.ignore_patterns(
                    ".git", ".venv", "build", "dist", "*.egg-info", "__pycache__"
                ),
            )
            uv = shutil.which("uv")
            command = (
                [uv, "build", "--wheel", "--out-dir", str(temporary_path), str(source_copy)]
                if uv
                else [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    str(source_copy),
                    "--no-deps",
                    "--wheel-dir",
                    temporary,
                ]
            )
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
            wheels = list(Path(temporary).glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as wheel:
                names = wheel.namelist()
                self.assertIn(f"core/chocolatey/assets/{SMOKE_NUPKG}", names)
                self.assertNotIn("core/chocolatey/assets.py", names)

    def test_local_lifecycle_step_precedes_user_package_install(self):
        steps = _steps()
        descriptions = [step.description for step in steps]
        smoke_index = descriptions.index("Prove Chocolatey local package lifecycle")
        package_index = descriptions.index("Install Chocolatey packages: 7zip")
        self.assertLess(smoke_index, package_index)
        smoke = "\n".join(steps[smoke_index].commands)
        self.assertIn(SMOKE_NUPKG, smoke)
        self.assertIn("--source \"$smoke_feed\"", smoke)
        self.assertIn('"${choco_package_launcher[@]}" install \\\n  cage-chocolatey-smoke', smoke)
        self.assertIn('"${choco_package_launcher[@]}" uninstall \\\n  cage-chocolatey-smoke', smoke)
        self.assertIn("CFW_CHOCOLATEY_QUERY_LAUNCHER", smoke)
        self.assertIn("CFW_CHOCOLATEY_PACKAGE_LAUNCHER", smoke)
        self.assertIn('"${choco_package_launcher[@]}" install', smoke)
        self.assertIn('"${choco_package_launcher[@]}" uninstall', smoke)
        self.assertEqual(smoke.count("--use-system-powershell"), 3)
        self.assertIn("chocolatey-smoke.sentinel", smoke)
        self.assertIn("CAGE_CHOCOLATEY_SMOKE", smoke)
        self.assertIn("chocolatey-smoke.json", smoke)
        self.assertIn("choco --version after uninstall", smoke)
        self.assertIn("initialStateClean", smoke)
        self.assertNotIn("community.chocolatey.org", smoke)

    def test_bootstrap_only_fixture_plans_until_a_runtime_is_released(self):
        manifest = load_manifest(ROOT / "tests/fixtures/chocolatey-bootstrap-smoke.cage.yaml")
        steps = manifest.modules[0].build()
        descriptions = [step.description for step in steps]

        self.assertEqual(getattr(manifest.modules[0], "install"), {"packages": []})
        self.assertIn("Require released CFW prepared prefix", descriptions)
        self.assertIn("Prove Chocolatey local package lifecycle", descriptions)
        self.assertFalse(any(name.startswith("Install Chocolatey packages:") for name in descriptions))

        workflow = (ROOT / ".github/workflows/chocolatey-smoke.yml").read_text(encoding="utf-8")
        self.assertIn("Check for released CFW runtime", workflow)
        self.assertIn("runtime-profile:", workflow)
        self.assertIn("image: ${{ steps.runtime.outputs.image }}", workflow)
        self.assertIn("CAGE_RUNTIME_IMAGE: ${{ needs.runtime-profile.outputs.image }}", workflow)
        self.assertIn("needs: runtime-profile", workflow)
        self.assertIn("if: needs.runtime-profile.outputs.available == 'true'", workflow)
        self.assertIn("exit 78", workflow)
        self.assertNotIn("if: steps.runtime.outputs.available == 'true'", workflow)
        self.assertIn("DEFAULT_CFW_RUNTIME_ARTIFACT", workflow)
        self.assertIn("CFW runtime evidence", workflow)
        self.assertIn("chocolatey-diagnostic.json", workflow)
        self.assertIn("chocolatey-feature-policy.json", workflow)
        self.assertIn("chocolatey-smoke.json", workflow)
        self.assertNotIn("KB3AIK_EN.iso", workflow)
        self.assertNotIn("wmf-dpx-extract.log", workflow)
        self.assertNotIn("powershell-engine.json", workflow)

    def test_lifecycle_outer_timeouts_cover_cumulative_inner_probes(self):
        steps = {step.description: step for step in _steps()}
        self.assertEqual(steps["Diagnose Chocolatey readiness"].timeout, 600)
        self.assertEqual(steps["Verify Chocolatey external-host policy"].timeout, 360)
        self.assertEqual(steps["Prove Chocolatey local package lifecycle"].timeout, 1800)

    def test_runtime_profile_includes_smoke_package_hash(self):
        record = "\n".join(_steps()[0].commands)
        self.assertIn(asset_sha256(SMOKE_NUPKG), record)


class ChocolateyDiagnosticTierTests(unittest.TestCase):
    def test_verification_has_required_advisory_and_failure_only_tiers(self):
        verify = load_asset("verify-chocolatey.sh")
        self.assertIn('"required"', verify)
        self.assertIn('"advisory"', verify)
        self.assertIn('"failureOnly"', verify)
        self.assertIn('"failedChecks"', verify)
        self.assertIn('"returnCodes"', verify)
        self.assertIn('"chocoVersion": int(version_rc)', verify)
        self.assertIn('CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-20s', verify)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", verify)
        self.assertIn('if [ "$required_status" != "passed" ]', verify)
        helper = load_asset("failure-diagnostics.sh")
        self.assertIn("CAGE_CHOCOLATEY_FAILURE_INVENTORY_TIMEOUT", helper)
        self.assertIn("/proc", helper)
        self.assertIn("choco-live-process-tree.log", helper)
        self.assertNotIn("ps -eo", helper)

    def test_advisory_checks_do_not_determine_overall_status(self):
        verify = load_asset("verify-chocolatey.sh")
        self.assertIn('"status": "passed" if not failed else "failed"', verify)
        self.assertNotIn('"status": "passed" if all(checks.values()) else "failed"', verify)

    def test_package_policy_uses_command_confirmation_only(self):
        policy = load_asset("feature-policy.sh")
        package = load_asset("install-package.sh")
        self.assertNotIn("feature disable", policy)
        self.assertNotIn("feature enable", policy)
        self.assertIn("{{POWERSHELL_HOST_POLICY}}", policy)
        self.assertIn("{{ALLOW_GLOBAL_CONFIRMATION_POLICY}}", policy)
        self.assertIn("feature-list.log", policy)
        self.assertIn("^{{POWERSHELL_HOST_FEATURE}}\\|(disabled|false)", policy)
        self.assertIn("^allowGlobalConfirmation\\|(disabled|false)", policy)
        self.assertNotIn("disable-powershellHost.log", policy)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", policy)
        self.assertIn("allowGlobalConfirmation", policy)
        self.assertIn('"${choco_launcher[@]}" install', package)
        self.assertIn("{{PACKAGE_ARGS}} -y --use-system-powershell", package)
        self.assertIn("chocolatey-feature-policy.json", package)


if __name__ == "__main__":
    unittest.main()
