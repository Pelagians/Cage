"""Chocolatey prepared-runtime module tests."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from core.manifest import Manifest

_RUNTIME = {
    "id": "cfw-runtime-test",
    "url": "https://example.invalid/cfw-runtime-prefix.tar.gz",
    "evidenceUrl": "https://example.invalid/runtime.json",
    "manifestUrl": "https://example.invalid/cfw-runtime-manifest.json",
    "manifestSha256": "c" * 64,
    "wineImage": "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64,
    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
}


def _manifest(packages=None, *, include_runtime=True, provenance=None, **module_overrides):
    install = {"packages": packages if packages is not None else ["7zip"]}
    runtime_override = module_overrides.pop("runtimeArtifact", None)
    if runtime_override is not None:
        install["runtimeArtifact"] = runtime_override
    elif include_runtime:
        install["runtimeArtifact"] = dict(_RUNTIME)
    module = {"type": "chocolatey", "install": install}
    module.update(module_overrides)
    return Manifest.from_dict({
        "schemaVersion": "cage.app/v0",
        "name": "test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "11.0"},
        "modules": [module],
        "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
        "provenance": provenance or {},
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

    def test_chocolatey_preserves_package_intent_and_provenance(self):
        manifest = _manifest(
            ["7zip", "notepadplusplus"],
            provenance={"test": "value"},
        )
        self.assertEqual(manifest.modules[0].install["packages"], ["7zip", "notepadplusplus"])
        self.assertEqual(manifest.provenance, {"test": "value"})

    def test_chocolatey_claims_prepared_runtime_capabilities(self):
        capabilities = _manifest().modules[0].capabilities()
        self.assertEqual(capabilities, {
            "package-manager": "chocolatey",
            "prefix-foundation": "cfw-prepared-runtime",
        })

    def test_chocolatey_rejects_obsolete_bootstrap_field(self):
        with self.assertRaisesRegex(Exception, "unknown module field.*bootstrap"):
            _manifest(bootstrap="legacy-profile")

    def test_chocolatey_rejects_ambiguous_legacy_source_field(self):
        with self.assertRaisesRegex(Exception, "unknown module field.*source"):
            _manifest(source="https://example.invalid/legacy-feed")

    def test_chocolatey_package_source_is_explicit_and_serialized(self):
        feed = "https://example.invalid/chocolatey-feed"
        module = _manifest(packageSource=feed).modules[0]

        self.assertEqual(module.to_dict()["packageSource"], feed)
        install = _commands_for(module.build(), "Install Chocolatey packages: 7zip")
        self.assertIn(feed, install)

    def test_chocolatey_rejects_unsafe_package_source_urls(self):
        for value in (
            "https://",
            "https://user:password@example.invalid/feed",
            "https://example.invalid/feed\nsecond-line",
            "https://example.invalid/$(touch-pwned)",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(Exception, "packageSource"):
                    _manifest(packageSource=value)

    def test_chocolatey_rejects_malformed_https_hosts(self):
        for value in (
            "https://exa mple.invalid/feed",
            "https://example..invalid/feed",
            "https://-example.invalid/feed",
            "https://example.invalid./feed",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(Exception, "packageSource"):
                    _manifest(packageSource=value)

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
        self.assertIn(_RUNTIME["evidenceUrl"], script)
        self.assertIn(_RUNTIME["manifestUrl"], script)
        self.assertIn(_RUNTIME["manifestSha256"], script)
        self.assertIn(_RUNTIME["wineImage"], script)
        self.assertIn("runtime-artifact.py", script)
        self.assertIn("cfw-chocolatey-runtime", script)
        self.assertNotIn("KB3AIK_EN.iso", script)
        self.assertNotIn("Win7AndW2K8R2-KB3191566-x64.zip", script)
        self.assertNotIn("PowerShell-7.5.5-win-x64.msi", script)
        self.assertNotIn("Install Synchro PowerShell layer", descriptions)
        self.assertNotIn("Install Windows PowerShell 5.1 backend", descriptions)

    def test_runtime_artifact_is_strictly_verified(self):
        steps = _manifest().modules[0].build()
        seed = _commands_for(steps, "Seed CFW prepared prefix")
        helper = (Path(__file__).resolve().parents[1] / "core/chocolatey/assets/runtime-artifact.py").read_text(encoding="utf-8")
        self.assertIn("cage_fetch_verified", seed)
        self.assertIn("sha256sum", seed)
        self.assertIn("runtime evidence status is not passed", helper)
        self.assertIn("cfw.prepared-runtime-manifest/v1", helper)
        self.assertIn("runtime manifest identity mismatch", helper)
        self.assertIn("runtime archive does not match manifest", helper)
        self.assertIn("runtime evidence does not match manifest", helper)
        self.assertIn("requiredProofs", helper)
        self.assertIn("interfaces", helper)
        self.assertNotIn('REQUIRED_CHECKS = {', helper)
        self.assertIn("unexpected CFW runtime provider", helper)
        self.assertIn("does not declare compatibility", helper)
        self.assertIn(".cage-prefix-seeded", seed)

    def test_unreleased_runtime_still_plans_but_real_build_fails_before_wineboot(self):
        with patch("core.modules.chocolatey.DEFAULT_CFW_RUNTIME_ARTIFACT", None):
            steps = _manifest(include_runtime=False).modules[0].build()
        seed = next(step for step in steps if step.kind == "prefix-seed")
        script = "\n".join(seed.commands)
        self.assertEqual(seed.description, "Require released CFW prepared prefix")
        self.assertIn("no released CFW prepared runtime is pinned", script)
        self.assertIn("exit 65", script)
        self.assertFalse(seed.metadata["runtimeAvailable"])

    def test_runtime_artifact_rejects_incomplete_hash(self):
        manifest = _manifest()
        manifest.modules[0].install["runtimeArtifact"]["manifestSha256"] = "abc"
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("complete lowercase sha256", str(ctx.exception))

    def test_runtime_artifact_requires_digest_pinned_wine_image(self):
        manifest = _manifest()
        manifest.modules[0].install["runtimeArtifact"]["wineImage"] = "ghcr.io/pelagians/cage-wine:11.0"
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("digest-pinned", str(ctx.exception))

    def test_runtime_artifact_rejects_unsafe_profile_fields_during_manifest_parse(self):
        cases = (
            ("id", "../../escape"),
            ("id", "runtime$(touch /tmp/pwned)"),
            ("url", "https://example.invalid/$(touch /tmp/pwned)"),
            ("evidenceUrl", "file:///tmp/evidence\nsecond-line"),
            ("manifestUrl", "/tmp/manifest;touch-pwned"),
            ("wineVersions", ["wine-11.0$(touch /tmp/pwned)"]),
        )
        for field, value in cases:
            runtime = dict(_RUNTIME)
            runtime[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(Exception):
                    _manifest(runtimeArtifact=runtime)

    def test_rendered_seed_embeds_encoded_profile_not_raw_urls(self):
        steps = _manifest().modules[0].build()
        seed = _commands_for(steps, "Seed CFW prepared prefix")
        self.assertIn("CFW_RUNTIME_PROFILE_BASE64", seed)
        self.assertIn("CFW_RUNTIME_HELPER_BASE64", seed)
        self.assertNotIn(_RUNTIME["url"], seed)
        self.assertNotIn(_RUNTIME["manifestUrl"], seed)

    def test_default_runtime_profile_resolves_to_its_pinned_image(self):
        from builder.executor import _required_cfw_runtime_image

        with patch("core.modules.chocolatey.DEFAULT_CFW_RUNTIME_ARTIFACT", dict(_RUNTIME)):
            manifest = _manifest(include_runtime=False)
            self.assertEqual(_required_cfw_runtime_image(manifest), _RUNTIME["wineImage"])

    def test_default_runtime_profile_is_materialized_in_serialized_manifest(self):
        with patch("core.modules.chocolatey.DEFAULT_CFW_RUNTIME_ARTIFACT", dict(_RUNTIME)):
            manifest = _manifest(include_runtime=False)
            serialized = manifest.to_dict()

        artifact = serialized["modules"][0]["install"]["runtimeArtifact"]
        self.assertEqual(artifact, _RUNTIME)

    def test_released_default_runtime_profile_is_pinned_to_cfw_v102(self):
        from core.modules.chocolatey import (
            DEFAULT_CFW_RUNTIME_ARTIFACT,
            DEFAULT_CFW_RUNTIME_PROFILE_ID,
        )

        self.assertIsNotNone(DEFAULT_CFW_RUNTIME_ARTIFACT)
        assert DEFAULT_CFW_RUNTIME_ARTIFACT is not None
        self.assertEqual(
            DEFAULT_CFW_RUNTIME_PROFILE_ID,
            "cfw-chocolatey-2.6.0-powershell-7.5.5-synchro-4.2.0",
        )
        self.assertEqual(DEFAULT_CFW_RUNTIME_ARTIFACT["id"], DEFAULT_CFW_RUNTIME_PROFILE_ID)
        self.assertEqual(
            DEFAULT_CFW_RUNTIME_ARTIFACT["manifestSha256"],
            "c3ef9da40ce4fa40413e1ea1918dc040c46eb266721180e6d9ee3c4a0606593d",
        )
        self.assertEqual(
            DEFAULT_CFW_RUNTIME_ARTIFACT["wineImage"],
            "ghcr.io/pelagians/cage-wine@sha256:b8462dedb8f4dc6e48305af5a4485c29796e5d7c292272b8492fb763b6b59224",
        )
        for field in ("url", "evidenceUrl", "manifestUrl"):
            self.assertIn("/cfw-runtime-v1.0.2/", DEFAULT_CFW_RUNTIME_ARTIFACT[field])

    def test_multiple_chocolatey_modules_are_rejected_before_duplicate_seeding(self):
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "duplicate-foundation",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"], "runtimeArtifact": dict(_RUNTIME)}},
                {"type": "chocolatey", "install": {"packages": ["git"], "runtimeArtifact": dict(_RUNTIME)}},
            ],
        }
        with self.assertRaisesRegex(Exception, "exactly one Chocolatey module"):
            Manifest.from_dict(data)

    def test_package_install_uses_canonical_choco_and_disabled_internal_host(self):
        steps = _manifest(["7zip", "notepadplusplus"]).modules[0].build()
        package = _commands_for(steps, "Install Chocolatey packages: 7zip notepadplusplus")
        policy = _commands_for(steps, "Verify Chocolatey external-host policy")
        self.assertIn("CFW_CHOCOLATEY_PREFIX_PATH", package)
        self.assertIn("CFW_CHOCOLATEY_WINDOWS_PATH", package)
        self.assertNotIn("ProgramData/tools/chocolateyInstall/choco.exe", package)
        self.assertIn("CFW_CHOCOLATEY_PACKAGE_LAUNCHER", package)
        self.assertIn('"${choco_launcher[@]}" install', package)
        self.assertIn("7zip notepadplusplus -y --use-system-powershell", package)
        self.assertIn("policy_status", package)
        self.assertNotIn("feature disable", policy)
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

    def test_runtime_artifact_requires_producer_declared_environment(self):
        runtime = dict(_RUNTIME)
        runtime.pop("environment")
        with self.assertRaisesRegex(Exception, "runtimeArtifact.environment"):
            _manifest([], runtimeArtifact=runtime)

    def test_phase_one_rejects_non_wine_11_cfw_runtime(self):
        runtime = dict(_RUNTIME)
        runtime["wineVersions"] = ["wine-9.0"]
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "wrong-wine",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "9.0"},
            "modules": [{"type": "chocolatey", "install": {
                "packages": [], "runtimeArtifact": runtime,
            }}],
        }
        with self.assertRaisesRegex(Exception, "Phase 1.*Wine 11"):
            Manifest.from_dict(data)

    def test_multiple_chocolatey_modules_require_one_identical_cfw_artifact(self):
        first = dict(_RUNTIME)
        second = {**_RUNTIME, "id": "cfw-runtime-other", "manifestSha256": "e" * 64}
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "conflicting-cfw",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"], "runtimeArtifact": first}},
                {"type": "chocolatey", "install": {"packages": ["git"], "runtimeArtifact": second}},
            ],
        }
        with self.assertRaisesRegex(Exception, "conflicting CFW prepared runtimes"):
            Manifest.from_dict(data)

    def test_chocolatey_rejects_option_like_package_names(self):
        for package in ("-s", "--source"):
            with self.subTest(package=package), self.assertRaisesRegex(Exception, "must begin with"):
                _manifest([package])

    def test_chocolatey_assets_inherit_producer_dll_policy(self):
        assets = Path(__file__).resolve().parents[1] / "core/chocolatey/assets"
        for name in ("verify-chocolatey.sh", "feature-policy.sh", "smoke-lifecycle.sh", "install-package.sh"):
            with self.subTest(name=name):
                self.assertNotIn("unset WINEDLLOVERRIDES", (assets / name).read_text(encoding="utf-8"))

    def test_chocolatey_rejects_shell_like_package_names(self):
        with self.assertRaises(Exception) as ctx:
            _manifest(["7zip; rm -rf /"])
        self.assertIn("must begin with a letter or number", str(ctx.exception))

    def test_chocolatey_rejects_non_string_package_names(self):
        with self.assertRaises(Exception) as ctx:
            _manifest(["7zip", 42])
        self.assertIn("install.packages", str(ctx.exception))

    def test_chocolatey_accepts_custom_package_source_url(self):
        manifest = _manifest(packageSource="https://custom.choco.source/")
        script = _all_commands(manifest.modules[0].build())
        self.assertIn(" -s 'https://custom.choco.source/'", script)

    def test_standalone_powershell_compatibility_is_not_a_cage_module(self):
        root = Path(__file__).resolve().parents[1]
        manifest_data = {
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "11.0"},
            "modules": [{"type": "powershell-wrapper", "version": "7"}],
            "launch": {"entrypoint": "C:/App.exe"},
        }
        with self.assertRaises(Exception) as ctx:
            Manifest.from_dict(manifest_data)
        self.assertIn("unknown module type", str(ctx.exception))
        for relative in (
            "core/modules/powershell_engine.py",
            "core/modules/powershell_wrapper.py",
            "core/powershell_wrapper_assets.py",
            "container/common/cage-powershell-runtime-smoke.sh",
            "builder/pipeline_old.py",
            ".github/workflows/cfw-expand-diagnostic.yml",
            ".github/workflows/inspect-mscoree-update.yml",
            "tests/scripts/aik-winpe-range-diagnostic.sh",
        ):
            self.assertFalse((root / relative).exists(), relative)
        tests_workflow = (root / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        containers_workflow = (root / ".github/workflows/containers.yml").read_text(encoding="utf-8")
        self.assertNotIn("cfw-expand-source-diagnostic", tests_workflow)
        self.assertNotIn("mscoree-update-diagnostic", tests_workflow)
        self.assertNotIn("cage-powershell-runtime-smoke", containers_workflow)

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
