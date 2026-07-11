"""Tests for the immutable layered Chocolatey bootstrap boundary."""
from __future__ import annotations

import dataclasses
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.chocolatey.assets import asset_sha256, load_asset
from core.chocolatey.profile import (
    DEFAULT_BOOTSTRAP_PROFILE_ID,
    get_bootstrap_profile,
)
from core.manifest import Manifest, ManifestError


ROOT = Path(__file__).resolve().parents[1]


def _manifest(**module_overrides):
    module = {
        "type": "chocolatey",
        "install": {"packages": ["7zip"]},
    }
    module.update(module_overrides)
    return Manifest.from_dict({
        "schemaVersion": "cage.app/v0",
        "name": "profile-test",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "11.0"},
        "modules": [module],
        "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
    })


class ChocolateyBootstrapProfileTests(unittest.TestCase):
    def test_builtin_profile_is_frozen_complete_and_layer_named(self):
        profile = get_bootstrap_profile(DEFAULT_BOOTSTRAP_PROFILE_ID)

        self.assertTrue(dataclasses.is_dataclass(profile))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            profile.id = "mutated"  # type: ignore[misc]
        self.assertEqual(
            profile.id,
            "cfw-v0.5c.755-noah.6-choco-2.6.0-synchro-r13",
        )
        self.assertEqual(profile.dotnet_profile, "dotnet48-cfw-r1")
        self.assertEqual(
            profile.dotnet_installer_sha256,
            "95889d6de3f2070c07790ad6cf2000d33d9a1bdfc6a381725ab82ab1c314fd53",
        )
        self.assertEqual(profile.chocolatey_for_wine_version, "v0.5c.755-noah.6")
        self.assertEqual(profile.chocolatey_for_wine_installer_version, "0.5c.755")
        self.assertEqual(
            profile.chocolatey_for_wine_url,
            "https://github.com/noahgiroux/Chocolatey-for-wine/releases/download/v0.5c.755-noah.6/Chocolatey-for-wine.7z",
        )
        self.assertEqual(
            profile.chocolatey_for_wine_sha256,
            "25c2e3cd544c7f83e9c196a5b8b0f98e020b4f5e24f19de30ea6ceec585d0792",
        )
        self.assertEqual(profile.upstream_project, "noahgiroux/Chocolatey-for-wine")
        self.assertEqual(profile.upstream_tag, "v0.5c.755-noah.6")
        self.assertEqual(profile.chocolatey_version, "2.6.0")
        # This remains the transitional bootstrap MSI. Cage replaces it with
        # the canonical 7.4.11 ZIP engine immediately after bootstrap.
        self.assertEqual(profile.powershell_version, "7.5.5")
        self.assertEqual(profile.powershell_host_feature, "powershellHost")
        self.assertEqual(profile.powershell_host, "disabled")
        self.assertEqual(profile.allow_global_confirmation, "disabled")
        self.assertEqual(profile.revision, "r13")
        for name, value in profile.to_dict().items():
            if name.endswith("Sha256"):
                self.assertRegex(value, r"^[0-9a-f]{64}$", name)

    def test_unknown_or_incomplete_bootstrap_profiles_are_rejected(self):
        manifest = _manifest(bootstrap="missing-profile")

        with self.assertRaisesRegex(Exception, "unknown Chocolatey bootstrap profile"):
            manifest.modules[0].build()

    def test_legacy_independent_bootstrap_component_fields_are_rejected(self):
        for field, value in (("version", "v0.5c.755"), ("sha256", "0" * 64)):
            with self.subTest(field=field):
                with self.assertRaises((ManifestError, Exception)) as ctx:
                    _manifest(**{field: value})
                self.assertIn("unknown module field", str(ctx.exception))

    def test_module_records_profile_assets_and_layer_provenance(self):
        module = _manifest().modules[0]
        steps = module.build()
        record = steps[0]
        command = "\n".join(record.commands)

        self.assertEqual(module.bootstrap, DEFAULT_BOOTSTRAP_PROFILE_ID)
        self.assertEqual(record.description, "Record layered Chocolatey bootstrap profile")
        self.assertIn("metadata/chocolatey-bootstrap.json", command)
        self.assertIn(asset_sha256("fetch-verified.sh"), command)
        self.assertIn("powershell-zip-7.4.11", command)
        self.assertIn("synchro-v4.2.0", command)
        self.assertIn("c3b4923d0f63188843bd2a15be64bca8f4a9902b", command)
        for step in steps:
            if "scriptAsset" in step.metadata:
                self.assertRegex(step.metadata["scriptSha256"], r"^[0-9a-f]{64}$")

    def test_module_uses_packaged_assets_instead_of_python_shell_templates(self):
        module_source = (ROOT / "core/modules/chocolatey.py").read_text(encoding="utf-8")
        base_source = (ROOT / "core/modules/base.py").read_text(encoding="utf-8")

        self.assertNotIn("cfw-v0.5c.755-noah", base_source)
        self.assertIn("DEFAULT_BOOTSTRAP_PROFILE_ID", base_source)
        self.assertNotIn("<<'PY'", module_source)
        self.assertNotIn("f'''set -eu", module_source)
        self.assertLess(len(module_source.splitlines()), 300)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"core.chocolatey.assets"', pyproject)
        self.assertIn('"*.sh"', pyproject)
        self.assertIn('"*.ps1"', pyproject)


class ChocolateyAssetContractTests(unittest.TestCase):
    def test_all_layer_assets_are_versioned_and_hashable(self):
        names = [
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "bootstrap.sh",
            "install-profile-fragments.sh",
            "verify-powershell-layer.sh",
            "verify-chocolatey.sh",
            "feature-policy.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
            "profile-20-chocolatey.ps1",
            "profile-30-cfw-winetricks.ps1",
            "profile-40-cfw-command-adapters.ps1",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(load_asset(name).strip())
                self.assertRegex(asset_sha256(name), r"^[0-9a-f]{64}$")

        legacy = {
            "install-mscoree.sh",
            "install-dotnet481.sh",
            "install-powershell-wrapper.sh",
            "prepare-registry.sh",
            "promote-chocolatey.sh",
            "powershell-msi.sh",
            "prepare-data.sh",
            "upstream-bootstrap.sh",
        }
        assets_dir = ROOT / "core/chocolatey/assets"
        self.assertFalse(legacy & {path.name for path in assets_dir.glob("*.sh")})

    def test_profile_fragments_are_additive(self):
        for name in (
            "profile-20-chocolatey.ps1",
            "profile-30-cfw-winetricks.ps1",
            "profile-40-cfw-command-adapters.ps1",
        ):
            text = load_asset(name)
            self.assertNotIn("Out-File $PROFILE", text)
            self.assertNotIn("New-Item -Path $PROFILE", text)
            self.assertNotIn("WindowsPowerShell\\v1.0\\powershell.exe", text)

    def test_verified_fetch_uses_content_addressing_locking_and_atomic_promotion(self):
        helper = load_asset("fetch-verified.sh")

        self.assertIn("blobs/sha256", helper)
        self.assertIn("flock", helper)
        self.assertIn(".part", helper)
        self.assertIn("sha256sum", helper)
        self.assertIn("--connect-timeout", helper)
        self.assertIn("--max-time", helper)
        self.assertIn('mv "$part" "$blob"', helper)
        self.assertIn('rm -f "$blob"', helper)
        self.assertIn("destination_actual", helper)
        self.assertIn("profile_lock", helper)

    def test_verified_fetch_replaces_a_corrupt_cached_blob(self):
        payload = b"verified-bootstrap-payload\n"
        digest = hashlib.sha256(payload).hexdigest()
        helper = load_asset("fetch-verified.sh")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            curl = fake_bin / "curl"
            curl.write_text(
                "#!/bin/sh\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = --output ]; then shift; output=$1; fi\n"
                "  shift\n"
                "done\n"
                "printf 'verified-bootstrap-payload\\n' > \"$output\"\n",
                encoding="utf-8",
            )
            curl.chmod(0o755)
            runner = root / "run.sh"
            runner.write_text(
                "#!/bin/bash\nset -eu\n" + helper + "\n"
                f"cage_fetch_verified https://example.invalid/payload {digest} "
                f"{root / 'output.bin'} test-profile\n",
                encoding="utf-8",
            )
            runner.chmod(0o755)
            environment = {
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "CAGE_MODULE_CACHE_DIR": str(root / "cache"),
            }

            subprocess.run([str(runner)], env=environment, check=True)
            blob = root / "cache" / "blobs" / "sha256" / digest
            self.assertEqual(blob.read_bytes(), payload)
            self.assertEqual((root / "output.bin").read_bytes(), payload)

            blob.write_bytes(b"corrupt")
            subprocess.run([str(runner)], env=environment, check=True)
            self.assertEqual(blob.read_bytes(), payload)
            self.assertEqual((root / "output.bin").read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
