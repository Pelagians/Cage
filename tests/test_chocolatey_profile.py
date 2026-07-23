"""Tests for Cage's prepared CFW runtime consumer boundary."""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.chocolatey.assets import asset_sha256, load_asset
from core.manifest import Manifest, ManifestError

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = {
    "id": "cfw-runtime-test",
    "url": "https://example.invalid/cfw-runtime-prefix.tar.gz",
    "evidenceUrl": "https://example.invalid/runtime.json",
    "manifestUrl": "https://example.invalid/cfw-runtime-manifest.json",
    "manifestSha256": "c" * 64,
    "wineImage": "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64,
    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
}


def _manifest(**module_overrides):
    module = {
        "type": "chocolatey",
        "install": {"packages": ["7zip"], "runtimeArtifact": dict(RUNTIME)},
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


class ChocolateyRuntimeProfileTests(unittest.TestCase):
    def test_runtime_profile_is_recorded_without_cfw_payload_details(self):
        steps = _manifest().modules[0].build()
        record = steps[0]
        command = "\n".join(record.commands)

        self.assertEqual(record.description, "Record CFW prepared runtime profile")
        self.assertIn("metadata/chocolatey-runtime-profile.json", command)
        self.assertIn(RUNTIME["id"], command)
        self.assertIn(RUNTIME["manifestSha256"], command)
        self.assertNotIn("external-windows-powershell", command)
        self.assertNotIn("packageExecutionHost", command)
        self.assertNotIn("KB3AIK_EN.iso", command)
        self.assertNotIn("KB3191566", command)
        self.assertNotIn("KB958488", command)
        for step in steps:
            if "scriptAsset" in step.metadata:
                self.assertRegex(step.metadata["scriptSha256"], r"^[0-9a-f]{64}$")

    def test_legacy_independent_bootstrap_fields_are_rejected(self):
        for field, value in (("version", "v0.5c.755"), ("sha256", "0" * 64)):
            with self.subTest(field=field):
                with self.assertRaises((ManifestError, Exception)) as ctx:
                    _manifest(**{field: value})
                self.assertIn("unknown module field", str(ctx.exception))

    def test_consumer_module_uses_packaged_assets_not_embedded_cfw_installers(self):
        module_source = (ROOT / "core/modules/chocolatey.py").read_text(encoding="utf-8")
        base_source = (ROOT / "core/modules/base.py").read_text(encoding="utf-8")

        self.assertNotIn("cfw-v0.5c.755-noah", base_source)
        self.assertNotIn("DEFAULT_BOOTSTRAP_PROFILE_ID", base_source)
        self.assertNotIn("DEFAULT_CFW_RUNTIME_PROFILE_ID", base_source)
        self.assertNotIn("get_bootstrap_profile", module_source)
        self.assertNotIn("choc_install.ps1", module_source)
        self.assertNotIn("install-powershell51", module_source)
        self.assertNotIn("install-native-mscoree", module_source)
        self.assertNotIn("install-dpx-helper", module_source)
        self.assertLess(len(module_source.splitlines()), 325)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"core.chocolatey.assets"', pyproject)
        self.assertIn('"*.sh"', pyproject)


class ChocolateyAssetContractTests(unittest.TestCase):
    def test_only_consumer_owned_assets_are_required(self):
        names = [
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "seed-cfw-runtime.sh",
            "runtime-artifact.py",
            "verify-chocolatey.sh",
            "feature-policy.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(load_asset(name).strip())
                self.assertRegex(asset_sha256(name), r"^[0-9a-f]{64}$")

        module_source = (ROOT / "core/modules/chocolatey.py").read_text(encoding="utf-8")
        assets_dir = ROOT / "core/chocolatey/assets"
        for removed in (
            "assembly-inventory.cs",
            "assembly-inventory.exe",
            "bootstrap.sh",
            "finalize-cfw-runtime.sh",
            "install-dpx-helper.sh",
            "install-native-mscoree.sh",
            "install-powershell51.sh",
            "assembly_inventory.py",
            "install-profile-fragments.sh",
            "profile-20-chocolatey.ps1",
            "profile-30-cfw-winetricks.ps1",
            "profile-40-cfw-command-adapters.ps1",
            "verify-powershell-layer.sh",
        ):
            self.assertNotIn(f'"{removed}"', module_source)
            self.assertFalse((assets_dir / removed).exists(), removed)

    def test_seed_asset_verifies_archive_evidence_and_prefix_outputs(self):
        seed = load_asset("seed-cfw-runtime.sh")
        helper = load_asset("runtime-artifact.py")
        self.assertIn("CFW_RUNTIME_PROFILE_BASE64", seed)
        self.assertIn("cfw.prepared-runtime-manifest/v1", helper)
        self.assertIn("runtime archive does not match manifest", helper)
        self.assertIn("runtime evidence does not match manifest", helper)
        self.assertIn("runtime evidence status is not passed", helper)
        self.assertIn("requiredProofs", helper)
        self.assertIn("interfaces", helper)
        self.assertNotIn('REQUIRED_CHECKS = {', helper)
        self.assertIn("extract_prepared_prefix", helper)
        self.assertNotIn("tar -xzf", seed)
        self.assertIn("CFW_CHOCOLATEY_PREFIX_PATH", seed)
        self.assertIn("CFW_CHOCOLATEY_WINDOWS_PATH", seed)
        self.assertIn('ln -s / "$dosdevices/z:"', seed)
        self.assertIn("ephemeral build prefix", seed)
        self.assertIn(".cage-prefix-seeded", seed)

    def test_verified_fetch_uses_content_addressing_locking_and_atomic_promotion(self):
        helper = load_asset("fetch-verified.sh")
        self.assertIn("blobs/sha256", helper)
        self.assertIn("flock", helper)
        self.assertIn(".part", helper)
        self.assertIn("sha256sum", helper)
        self.assertIn("--connect-timeout", helper)
        self.assertIn("--max-time", helper)
        self.assertIn("--silent", helper)
        self.assertIn("--show-error", helper)
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
