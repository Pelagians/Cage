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
        self.assertEqual(profile.id, "cfw-v0.5c.755-choco-2.6.0-dotnet481-wrapper-r5")
        self.assertEqual(profile.dotnet_profile, "dotnet481-cfw-r1")
        self.assertEqual(profile.chocolatey_for_wine_version, "v0.5c.755")
        self.assertEqual(profile.chocolatey_version, "2.6.0")
        self.assertEqual(profile.powershell_version, "7.5.5")
        self.assertEqual(profile.powershell_host_feature, "powershellHost")
        self.assertEqual(profile.powershell_host, "disabled")
        self.assertEqual(profile.allow_global_confirmation, "disabled")
        self.assertEqual(profile.revision, "r5")
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

        self.assertNotIn("<<'PY'", module_source)
        self.assertNotIn('f\'\'\'set -eu', module_source)
        self.assertLess(len(module_source.splitlines()), 300)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"core.chocolatey.assets"', pyproject)
        self.assertIn('"*.sh"', pyproject)

    def test_native_mscoree_update_is_frozen_and_installed_before_dotnet(self):
        profile = get_bootstrap_profile()
        self.assertEqual(
            profile.mscoree_update_sha256,
            "a5f4243ce8b07c9222284fd8ff6f7e742d934c57c89de9cab5d88c74402264e3",
        )
        self.assertTrue(profile.mscoree_update_url.startswith("https://"))
        script = load_asset("install-mscoree.sh")
        self.assertIn("cage_fetch_verified", script)
        self.assertIn("0x8664", script)
        self.assertIn("0x014C", script)
        self.assertNotIn("'*mscoree.dll'", script)
        self.assertIn("chocolatey-mscoree.json", script)
        descriptions = [
            step.description
            for step in _manifest(install={"packages": []}).modules[0].build()
        ]
        self.assertLess(
            descriptions.index("Install native .NET loader"),
            descriptions.index("Install frozen dotnet481 profile"),
        )

    def test_chocolatey_profile_freezes_powershell_wrapper_assets(self):
        profile = get_bootstrap_profile()

        self.assertEqual(profile.powershell_wrapper_version, "v4.2.0")
        self.assertRegex(profile.powershell_wrapper64_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(profile.powershell_wrapper32_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(profile.powershell_wrapper_profile_sha256, r"^[0-9a-f]{64}$")
        self.assertTrue(profile.powershell_wrapper_base_url.startswith("https://"))
        payload = profile.to_dict()
        self.assertEqual(payload["powershellWrapperVersion"], "v4.2.0")
        self.assertEqual(
            payload["powershellWrapper64Sha256"],
            profile.powershell_wrapper64_sha256,
        )

    def test_chocolatey_installs_and_verifies_wrapper_before_readiness(self):
        profile = get_bootstrap_profile()
        steps = _manifest(install={"packages": []}).modules[0].build()
        descriptions = [step.description for step in steps]
        wrapper_description = "Install Chocolatey PowerShell wrapper"

        self.assertIn(wrapper_description, descriptions)
        self.assertLess(
            descriptions.index("Prepare Wine registry for Chocolatey"),
            descriptions.index(wrapper_description),
        )
        self.assertLess(
            descriptions.index(wrapper_description),
            descriptions.index("Diagnose Chocolatey readiness"),
        )
        wrapper = "\n".join(
            next(step for step in steps if step.description == wrapper_description).commands
        )
        self.assertIn("cage_fetch_verified", wrapper)
        self.assertIn(profile.powershell_wrapper64_sha256, wrapper)
        self.assertIn(profile.powershell_wrapper32_sha256, wrapper)
        self.assertIn(profile.powershell_wrapper_profile_sha256, wrapper)
        self.assertIn("WindowsPowerShell/v1.0/powershell.exe", wrapper)
        self.assertIn("windows/syswow64/WindowsPowerShell/v1.0/powershell.exe", wrapper)
        self.assertIn("chocolatey-powershell-wrapper.json", wrapper)
        self.assertIn("wrapper64-sentinel.txt", wrapper)
        self.assertIn("wrapper32-sentinel.txt", wrapper)
        self.assertIn("CAGE-POWERSHELL-WRAPPER-64", wrapper)
        self.assertIn("CAGE-POWERSHELL-WRAPPER-32", wrapper)


class ChocolateyAssetContractTests(unittest.TestCase):
    def test_all_step_assets_are_versioned_and_hashable(self):
        names = [
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "powershell-msi.sh",
            "prepare-data.sh",
            "install-mscoree.sh",
            "install-dotnet481.sh",
            "install-powershell-wrapper.sh",
            "prepare-registry.sh",
            "promote-chocolatey.sh",
            "verify-chocolatey.sh",
            "feature-policy.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(load_asset(name).strip())
                self.assertRegex(asset_sha256(name), r"^[0-9a-f]{64}$")

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

    def test_dotnet_manifest_destination_is_a_directory_not_a_filename(self):
        script = load_asset("install-dotnet481.sh")
        embedded = script[
            script.index("import hashlib\n") : script.index("\nPY\n", script.index("import hashlib\n"))
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            drive = root / "drive"
            registry = root / "registry"
            payload.mkdir()
            drive.mkdir()
            registry.mkdir()

            def manifest(
                stem: str,
                name: str,
                destination: str,
                source_name: str | None = None,
            ) -> None:
                source_dir = payload / stem
                source_dir.mkdir()
                payload_name = source_name or name.replace("\\", "/").rsplit("/", 1)[-1]
                (source_dir / payload_name.lower()).write_bytes(name.encode("ascii"))
                source_attribute = (
                    f' sourceName="{source_name}"' if source_name is not None else ""
                )
                (payload / f"{stem}.manifest").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<assembly xmlns="urn:schemas-microsoft-com:asm.v3">\n'
                    '  <assemblyIdentity processorArchitecture="amd64" />\n'
                    f'  <file name="{name}" destinationPath="{destination}"{source_attribute} />\n'
                    '</assembly>\n',
                    encoding="utf-8",
                )

            manifest(
                "amd64_oracle_header",
                "OracleHeader.h",
                "$(runtime.inf)\\.NET Data Provider for Oracle\\",
            )
            manifest(
                "amd64_oracle_locale",
                "GAC\\OracleCounters.ini",
                "$(runtime.inf)\\.NET Data Provider for Oracle\\0000\\",
                source_name="OracleCounters.ini",
            )
            for relative in (
                "windows/system32/mscoree.dll",
                "windows/syswow64/mscoree.dll",
            ):
                marker = drive / relative
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_bytes(f"wine-prefix:{relative}".encode("ascii"))
            required = (
                "mscoreei.dll",
                "clr.dll",
                "clrjit.dll",
                "ucrtbase_clr0400.dll",
                "vcruntime140_clr0400.dll",
            )
            for architecture in ("amd64", "x86"):
                directory = payload / f"{architecture}_required"
                directory.mkdir()
                for name in required:
                    (directory / name).write_bytes(f"{architecture}:{name}".encode("ascii"))

            argv = [
                "embedded-dotnet-profile",
                str(payload),
                str(drive),
                str(registry),
                str(root / "profile.json"),
                "dotnet481-cfw-r1",
                "0" * 64,
            ]
            runner = (
                "import sys\n"
                f"sys.argv = {argv!r}\n"
                f"exec(compile({embedded!r}, 'install-dotnet481.sh', 'exec'), {{'__name__': '__main__'}})\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", runner],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            oracle = drive / "windows/inf/.NET Data Provider for Oracle"
            self.assertTrue((oracle / "OracleHeader.h").is_file())
            self.assertTrue((oracle / "0000/GAC/OracleCounters.ini").is_file())
            profile = json.loads((root / "profile.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [entry["destination"] for entry in profile["preservedFiles"]],
                [
                    "C:/windows/system32/mscoree.dll",
                    "C:/windows/syswow64/mscoree.dll",
                ],
            )

    def test_dotnet_profile_fails_closed_and_emits_install_manifest(self):
        script = load_asset("install-dotnet481.sh")

        self.assertIn("unknown required manifest token", script)
        self.assertIn("ambiguous dotnet481 source", script)
        self.assertIn("missing required dotnet481 source", script)
        self.assertIn("sha256", script)
        self.assertIn("chocolatey-dotnet-profile.json", script)
        self.assertIn("dotnet481-cfw-r1", script)
        self.assertNotIn("return matches[0]", script)
        self.assertNotRegex(script, re.compile(r"if src is None:\s+continue"))


if __name__ == "__main__":
    unittest.main()
