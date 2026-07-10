"""Phase 3 Chocolatey local package-lifecycle and diagnostic-tier contracts."""
from __future__ import annotations

import io
import runpy
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.chocolatey.assets import asset_sha256, load_asset, load_asset_bytes
from core.manifest import Manifest, load_manifest


ROOT = Path(__file__).resolve().parents[1]
SMOKE_NUPKG = "cage-chocolatey-smoke.0.1.0.nupkg"


def _steps():
    manifest = Manifest.from_dict({
        "schemaVersion": "cage.app/v0",
        "name": "smoke-test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "11.0"},
        "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}],
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
        self.assertIn("CAGE_CHOCOLATEY_SMOKE_RUN_ID", uninstall)

    def test_built_wheel_contains_smoke_nupkg(self):
        uv = shutil.which("uv")
        if uv is None:
            self.fail("uv is required for the wheel-content acceptance test")
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run(
                [uv, "build", "--wheel", "--out-dir", temporary],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            wheels = list(Path(temporary).glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as wheel:
                self.assertIn(
                    f"core/chocolatey/assets/{SMOKE_NUPKG}",
                    wheel.namelist(),
                )

    def test_local_lifecycle_step_precedes_user_package_install(self):
        steps = _steps()
        descriptions = [step.description for step in steps]

        smoke_index = descriptions.index("Prove Chocolatey local package lifecycle")
        package_index = descriptions.index("Install Chocolatey packages: 7zip")
        self.assertLess(smoke_index, package_index)
        smoke = "\n".join(steps[smoke_index].commands)
        self.assertIn(SMOKE_NUPKG, smoke)
        self.assertIn("--source \"$smoke_feed\"", smoke)
        self.assertIn("install cage-chocolatey-smoke", smoke)
        self.assertIn("uninstall cage-chocolatey-smoke", smoke)
        self.assertIn("chocolatey-smoke.sentinel", smoke)
        self.assertIn("CAGE_CHOCOLATEY_SMOKE", smoke)
        self.assertIn("chocolatey-smoke.json", smoke)
        self.assertIn("choco --version after uninstall", smoke)
        self.assertIn("CAGE_CHOCOLATEY_SMOKE_RUN_ID", smoke)
        self.assertIn("initialStateClean", smoke)
        self.assertIn("package-state-before.log", smoke)
        self.assertIn("package-state-after.log", smoke)
        self.assertIn("marker-absent-before.log", smoke)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", smoke)
        self.assertNotIn("community.chocolatey.org", smoke)

    def test_bootstrap_only_module_stops_after_local_lifecycle(self):
        manifest = load_manifest(
            ROOT / "tests/fixtures/chocolatey-bootstrap-smoke.cage.yaml"
        )
        descriptions = [step.description for step in manifest.modules[0].build()]

        self.assertEqual(getattr(manifest.modules[0], "install"), {"packages": []})
        self.assertIn("Prove Chocolatey local package lifecycle", descriptions)
        self.assertFalse(any(name.startswith("Install Chocolatey packages:") for name in descriptions))

        workflow = (
            ROOT / ".github/workflows/chocolatey-smoke.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("ghcr.io/pelagians/cage-wine:11.0", workflow)
        self.assertIn("--build-timeout 7200", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)

    def test_lifecycle_outer_timeouts_cover_cumulative_inner_probes(self):
        steps = {step.description: step for step in _steps()}

        self.assertEqual(steps["Diagnose Chocolatey readiness"].timeout, 600)
        self.assertEqual(steps["Apply Chocolatey feature policy"].timeout, 360)
        self.assertEqual(steps["Prove Chocolatey local package lifecycle"].timeout, 1800)

    def test_bootstrap_provenance_includes_smoke_package_hash(self):
        record = "\n".join(_steps()[0].commands)
        self.assertIn(asset_sha256(SMOKE_NUPKG), record)


class ChocolateyDiagnosticTierTests(unittest.TestCase):
    def test_verification_has_required_advisory_and_failure_only_tiers(self):
        verify = load_asset("verify-chocolatey.sh")

        self.assertIn('"required"', verify)
        self.assertIn('"advisory"', verify)
        self.assertIn('"failureOnly"', verify)
        self.assertIn('"failedChecks"', verify)
        self.assertIn("required_passed", verify)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", verify)
        helper = load_asset("failure-diagnostics.sh")
        self.assertIn("CAGE_CHOCOLATEY_FAILURE_INVENTORY_TIMEOUT", helper)
        self.assertIn("CAGE_CHOCOLATEY_FAILURE_INVENTORY_LIMIT", helper)
        self.assertNotIn("ps -ef", helper)
        self.assertIn("failureTrigger", helper)
        self.assertIn("if [ \"$required_status\" != \"passed\" ]", verify)
        failure_boundary = verify.index('if [ "$required_status" != "passed" ]')
        self.assertGreater(
            verify.index("cage_chocolatey_collect_failure_diagnostics", failure_boundary),
            failure_boundary,
        )
        self.assertIn("WINEDEBUG=+loaddll", helper)
        self.assertIn('> "$probe_dir/promoted-files.log"', helper)

    def test_advisory_checks_do_not_determine_overall_status(self):
        verify = load_asset("verify-chocolatey.sh")

        self.assertIn('"status": "passed" if required_passed else "failed"', verify)
        self.assertNotIn('"status": "passed" if all(checks.values()) else "failed"', verify)

    def test_promotion_constructs_state_without_running_chocolatey(self):
        promote = load_asset("promote-chocolatey.sh")

        self.assertNotIn("CAGE_CHOCOLATEY_VERIFY_TIMEOUT", promote)
        self.assertNotIn('wine "$choco_exe_win" --version', promote)
        self.assertNotIn("Continuing to diagnostic step", promote)

    def test_package_policy_uses_command_confirmation_only(self):
        policy = load_asset("feature-policy.sh")
        package = load_asset("install-package.sh")

        self.assertIn("feature disable --name={{POWERSHELL_HOST_FEATURE}}", policy)
        self.assertNotIn("feature enable -n allowGlobalConfirmation", policy)
        self.assertIn("{{POWERSHELL_HOST_POLICY}}", policy)
        self.assertIn("{{ALLOW_GLOBAL_CONFIRMATION_POLICY}}", policy)
        self.assertIn("feature-list.log", policy)
        self.assertIn("disable-powershellHost.log", policy)
        self.assertIn("cage_chocolatey_collect_failure_diagnostics", policy)
        self.assertIn("allowGlobalConfirmation", policy)
        self.assertIn("install {{PACKAGE_ARGS}} -y", package)
        self.assertIn("chocolatey-feature-policy.json", package)


if __name__ == "__main__":
    unittest.main()
