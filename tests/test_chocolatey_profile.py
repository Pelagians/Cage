"""Tests for the immutable Chocolatey bootstrap profile boundary."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.chocolatey.assets import asset_sha256, load_asset
from core.chocolatey.profile import (
    DEFAULT_BOOTSTRAP_PROFILE_ID,
    ChocolateyProfileError,
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
    def test_builtin_profile_is_frozen_complete_and_compatibility_set_named(self):
        profile = get_bootstrap_profile(DEFAULT_BOOTSTRAP_PROFILE_ID)

        self.assertTrue(dataclasses.is_dataclass(profile))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            profile.id = "mutated"  # type: ignore[misc]
        self.assertEqual(profile.id, "cfw-v0.5c.755-noah.2-choco-2.6.0-fork-r8")
        self.assertEqual(profile.dotnet_profile, "dotnet48-cfw-r1")
        self.assertEqual(profile.dotnet_installer_sha256, "95889d6de3f2070c07790ad6cf2000d33d9a1bdfc6a381725ab82ab1c314fd53")
        self.assertEqual(profile.chocolatey_for_wine_version, "v0.5c.755-noah.2")
        self.assertEqual(profile.chocolatey_for_wine_installer_version, "0.5c.755")
        self.assertEqual(
            profile.chocolatey_for_wine_url,
            "https://github.com/noahgiroux/Chocolatey-for-wine/releases/download/v0.5c.755-noah.2/Chocolatey-for-wine.7z",
        )
        self.assertEqual(
            profile.chocolatey_for_wine_sha256,
            "b973ca8557449d64791f82b724aea1ecc4d6a91d11d6c401f92a7ce33cb9029f",
        )
        self.assertEqual(profile.upstream_project, "noahgiroux/Chocolatey-for-wine")
        self.assertEqual(profile.chocolatey_version, "2.6.0")
        self.assertEqual(profile.powershell_version, "7.5.5")
        self.assertEqual(profile.powershell_host_feature, "powershellHost")
        self.assertEqual(profile.powershell_host, "disabled")
        self.assertEqual(profile.allow_global_confirmation, "disabled")
        self.assertFalse(any(key.startswith("powershellWrapper") for key in profile.to_dict()))
        self.assertEqual(profile.revision, "r8")
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

    def test_module_steps_record_profile_and_versioned_asset_hashes(self):
        module = _manifest().modules[0]
        steps = module.build()

        self.assertEqual(module.bootstrap, DEFAULT_BOOTSTRAP_PROFILE_ID)
        self.assertEqual(steps[0].description, "Record Chocolatey bootstrap profile")
        self.assertIn("metadata/chocolatey-bootstrap.json", "\n".join(steps[0].commands))
        self.assertIn(asset_sha256("fetch-verified.sh"), "\n".join(steps[0].commands))
        for step in steps:
            self.assertEqual(step.metadata["bootstrapProfile"], DEFAULT_BOOTSTRAP_PROFILE_ID)
            if "scriptAsset" in step.metadata:
                self.assertRegex(step.metadata["scriptSha256"], r"^[0-9a-f]{64}$")

    def test_module_uses_packaged_assets_instead_of_python_heredocs(self):
        module_source = (ROOT / "core/modules/chocolatey.py").read_text(encoding="utf-8")
        base_source = (ROOT / "core/modules/base.py").read_text(encoding="utf-8")

        self.assertNotIn("cfw-v0.5c.755-noah", base_source)
        self.assertIn("DEFAULT_BOOTSTRAP_PROFILE_ID", base_source)
        self.assertNotIn("<<'PY'", module_source)
        self.assertNotIn('f\'\'\'set -eu', module_source)
        self.assertLess(len(module_source.splitlines()), 300)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"core.chocolatey.assets"', pyproject)
        self.assertIn('"*.sh"', pyproject)





class ChocolateyAssetContractTests(unittest.TestCase):
    def test_all_step_assets_are_versioned_and_hashable(self):
        names = [
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "bootstrap.sh",
            "verify-chocolatey.sh",
            "feature-policy.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
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

    def test_verified_fetch_uses_content_addressing_locking_and_atomic_promotion(self):
        helper = load_asset("fetch-verified.sh")

        self.assertIn("blobs/sha256", helper)
        self.assertIn("flock", helper)
        self.assertIn(".part", helper)
        self.assertIn("sha256sum", helper)
        self.assertIn("--connect-timeout", helper)
        self.assertIn("--max-time", helper)
        self.assertIn("mv \"$part\" \"$blob\"", helper)
        self.assertIn("rm -f \"$blob\"", helper)
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
