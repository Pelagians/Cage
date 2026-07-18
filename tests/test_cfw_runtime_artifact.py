"""Executable security tests for CFW runtime verification and extraction."""
from __future__ import annotations

import hashlib
import io
import json
import os
import runpy
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.manifest import Manifest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "core/chocolatey/assets/runtime-artifact.py"
IMAGE = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64


def _helper():
    return runpy.run_path(str(HELPER))


def _records():
    profile = {
        "id": "cfw-runtime-test",
        "url": "file:///runtime.tar.gz",
        "evidenceUrl": "file:///runtime.json",
        "manifestUrl": "file:///manifest.json",
        "manifestSha256": "a" * 64,
        "wineImage": IMAGE,
        "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
    }
    bound = {
        "sourceRevision": "b" * 40,
        "contractSha256": "9" * 64,
        "installerSha256": "c" * 64,
        "runtimeInputsSha256": "e" * 64,
        "wine": {"image": IMAGE, "version": "wine-11.0", "architecture": "win64"},
    }
    manifest = {
        "schemaVersion": "cfw.prepared-runtime-manifest/v1",
        "contract": "cfw.compatibility-contract/v3",
        "status": "passed",
        "runtimeId": profile["id"],
        "archive": {"filename": "runtime.tar.gz", "sha256": "f" * 64, "bytes": 1},
        "runtimeEvidence": {"filename": "runtime.json", "sha256": "1" * 64},
        "requiredProofs": [
            "wineIdentity", "installer", "prePwshPolicy", "pathConversions", "pwsh", "preparedFinalizer", "featurePolicy",
            "chocolatey", "synchroX64", "synchroX86", "chocolateyLifecycle",
        ],
        "interfaces": {
            "chocolatey": {
                "windowsPath": r"C:\ProgramData\chocolatey\bin\choco.exe",
                "prefixRelativePath": "drive_c/ProgramData/chocolatey/bin/choco.exe",
            },
            "environment": {"WINEDLLOVERRIDES": ""},
        },
        **bound,
    }
    evidence = {
        "schemaVersion": "cfw.runtime-build/v2",
        "contract": "cfw.compatibility-contract/v3",
        "provider": "cfw-chocolatey-runtime",
        "status": "passed",
        "runtimeId": profile["id"],
        "checks": {name: True for name in (
            "wineIdentity", "installer", "prePwshPolicy", "pathConversions", "pwsh", "preparedFinalizer", "featurePolicy",
            "chocolatey", "synchroX64", "synchroX86", "chocolateyLifecycle",
        )},
        **bound,
    }
    return profile, manifest, evidence


class CfwRuntimeArtifactTests(unittest.TestCase):
    def test_verification_rejects_missing_required_provenance(self):
        verify = _helper()["validate_records"]
        for field in ("sourceRevision", "contractSha256", "installerSha256", "runtimeInputsSha256", "wine"):
            profile, manifest, evidence = _records()
            manifest.pop(field)
            evidence.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify(profile, manifest, evidence, "wine-11.0", IMAGE)

    def test_verification_rejects_missing_evidence_schema(self):
        verify = _helper()["validate_records"]
        profile, manifest, evidence = _records()
        evidence.pop("schemaVersion")
        with self.assertRaisesRegex(ValueError, "evidence schema"):
            verify(profile, manifest, evidence, "wine-11.0", IMAGE)

    def test_verification_rejects_mismatched_chocolatey_interface_paths(self):
        verify = _helper()["validate_records"]
        profile, manifest, evidence = _records()
        manifest["interfaces"]["chocolatey"]["windowsPath"] = "C:\\Unbound\\evil.exe"
        with self.assertRaisesRegex(ValueError, "representations do not match"):
            verify(profile, manifest, evidence, "wine-11.0", IMAGE)

    def test_verification_rejects_manifest_environment_mismatch(self):
        verify = _helper()["validate_records"]
        profile, manifest, evidence = _records()
        manifest["interfaces"]["environment"] = {"WINEDLLOVERRIDES": "mscoree="}
        with self.assertRaisesRegex(ValueError, "environment does not match profile"):
            verify(profile, manifest, evidence, "wine-11.0", IMAGE)

    def test_safe_extractor_rejects_cage_owned_metadata_paths(self):
        extract = _helper()["extract_prepared_prefix"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                member = tarfile.TarInfo(".cfw/runtime.json.part")
                member.type = tarfile.SYMTYPE
                member.linkname = "../drive_c/ProgramData/chocolatey/bin/choco.exe"
                tar.addfile(member)
            with self.assertRaisesRegex(ValueError, "reserved Cage metadata path"):
                extract(archive, root / "prefix")

    def test_safe_extractor_restores_previous_prefix_when_promotion_fails(self):
        extract = _helper()["extract_prepared_prefix"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                directory = tarfile.TarInfo("drive_c")
                directory.type = tarfile.DIRTYPE
                tar.addfile(directory)
            prefix = root / "prefix"
            prefix.mkdir()
            (prefix / "old.txt").write_text("old", encoding="utf-8")
            real_replace = os.replace
            calls = 0

            def fail_new_prefix(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated promotion failure")
                return real_replace(source, destination)

            with patch("os.replace", side_effect=fail_new_prefix):
                with self.assertRaisesRegex(OSError, "simulated promotion failure"):
                    extract(archive, prefix)

            self.assertEqual((prefix / "old.txt").read_text(encoding="utf-8"), "old")

    def test_safe_extractor_rejects_absolute_symlink(self):
        extract = _helper()["extract_prepared_prefix"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                link = tarfile.TarInfo("escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "/tmp/outside"
                tar.addfile(link)
            with self.assertRaisesRegex(ValueError, "unsafe symlink"):
                extract(archive, root / "prefix")
            self.assertFalse((root / "prefix").exists())

    def test_safe_extractor_rejects_special_members(self):
        extract = _helper()["extract_prepared_prefix"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                device = tarfile.TarInfo("device")
                device.type = tarfile.CHRTYPE
                tar.addfile(device)
            with self.assertRaisesRegex(ValueError, "unsupported archive member"):
                extract(archive, root / "prefix")

    def test_safe_extractor_rejects_hardlinks(self):
        extract = _helper()["extract_prepared_prefix"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                regular = tarfile.TarInfo("target")
                regular.size = 7
                tar.addfile(regular, io.BytesIO(b"payload"))
                link = tarfile.TarInfo("copy")
                link.type = tarfile.LNKTYPE
                link.linkname = "target"
                tar.addfile(link)
            with self.assertRaisesRegex(ValueError, "hardlinks are not supported"):
                extract(archive, root / "prefix")

    def test_safe_extractor_rejects_symlink_ancestor_aliases(self):
        extract = _helper()["extract_prepared_prefix"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                first = tarfile.TarInfo("target")
                first.size = 5
                tar.addfile(first, io.BytesIO(b"first"))
                alias = tarfile.TarInfo("alias")
                alias.type = tarfile.SYMTYPE
                alias.linkname = "."
                tar.addfile(alias)
                second = tarfile.TarInfo("alias/target")
                second.size = 6
                tar.addfile(second, io.BytesIO(b"second"))
            with self.assertRaisesRegex(ValueError, "symlink path conflicts"):
                extract(archive, root / "prefix")

    def test_safe_extractor_applies_member_limit_while_streaming(self):
        helper = _helper()
        helper["extract_prepared_prefix"].__globals__["MAX_MEMBERS"] = 1
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for name in ("one", "two"):
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    tar.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(ValueError, "too many members"):
                helper["extract_prepared_prefix"](archive, root / "prefix")

    def test_safe_extractor_promotes_only_valid_prefix(self):
        extract = _helper()["extract_prepared_prefix"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            payloads = {
                "drive_c/ProgramData/chocolatey/bin/choco.exe": b"choco",
                "drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe": b"x64",
                "drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe": b"x86",
            }
            with tarfile.open(archive, "w:gz") as tar:
                archive_root = tarfile.TarInfo(".")
                archive_root.type = tarfile.DIRTYPE
                tar.addfile(archive_root)
                for name, payload in payloads.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    member.mode = 0o755
                    tar.addfile(member, io.BytesIO(payload))
                dosdevices = tarfile.TarInfo("dosdevices")
                dosdevices.type = tarfile.DIRTYPE
                dosdevices.mode = 0o755
                tar.addfile(dosdevices)
                drive_c = tarfile.TarInfo("dosdevices/c:")
                drive_c.type = tarfile.SYMTYPE
                drive_c.linkname = "../drive_c"
                tar.addfile(drive_c)
            prefix = root / "prefix"
            extract(archive, prefix)
            for name, payload in payloads.items():
                self.assertEqual((prefix / name).read_bytes(), payload)
            self.assertEqual((prefix / "dosdevices/c:").resolve(), (prefix / "drive_c").resolve())

    def test_rendered_seed_executes_verified_local_runtime_end_to_end(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.tar.gz"
            payloads = {
                "drive_c/ProgramData/chocolatey/bin/choco.exe": b"choco",
                "drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe": b"x64",
                "drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe": b"x86",
            }
            with tarfile.open(archive, "w:gz") as tar:
                for name, payload in payloads.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    member.mode = 0o755
                    tar.addfile(member, io.BytesIO(payload))

            profile, manifest_record, evidence_record = _records()
            evidence_path = root / "runtime.json"
            evidence_path.write_text(json.dumps(evidence_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            manifest_record["archive"].update({"sha256": archive_digest, "bytes": archive.stat().st_size})
            manifest_record["runtimeEvidence"]["sha256"] = evidence_digest
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            profile.update({
                "url": str(archive),
                "evidenceUrl": str(evidence_path),
                "manifestUrl": str(manifest_path),
                "manifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            })
            cage_manifest = Manifest.from_dict({
                "schemaVersion": "cage.app/v0",
                "name": "runtime-seed-test",
                "version": "1.0.0",
                "runtime": {"provider": "wine", "version": "11.0"},
                "modules": [{"type": "chocolatey", "install": {
                    "packages": ["7zip"], "runtimeArtifact": profile,
                }}],
                "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
            })
            seed = next(
                step for step in cage_manifest.modules[0].build()
                if step.description == "Seed CFW prepared prefix"
            )
            command = "\n".join(seed.commands)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            wine = fake_bin / "wine"
            wine.write_text("#!/bin/sh\nprintf 'wine-11.0\\n'\n", encoding="utf-8")
            wine.chmod(0o755)
            prefix = root / "prefix"
            environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "WINEPREFIX": str(prefix),
                "CAGE_RUNTIME_IMAGE": IMAGE,
                "WINEDLLOVERRIDES": "",
                "CAGE_MODULE_CACHE_DIR": str(root / "cache"),
                "CAGE_BUNDLE_MOUNT": str(root / "bundle"),
            }

            subprocess.run(["bash", "-c", command], env=environment, check=True)

            self.assertEqual((prefix / next(iter(payloads))).read_bytes(), b"choco")
            self.assertTrue((prefix / ".cage-prefix-seeded").is_file())
            self.assertTrue((root / "bundle/metadata/cfw-runtime-manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
