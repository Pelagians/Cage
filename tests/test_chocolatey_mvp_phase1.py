"""Regression tests for the Chocolatey MVP Phase 1 artifact contract."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from artifact.bundle import create_bundle
from artifact.inspection import verify_bundle
from artifact.oci import OCIExportError, create_oci_export_plan
from builder.executor import (
    BuildResult,
    _resolve_public_chocolatey_package_receipt,
    _write_host_chocolatey_package_evidence,
    execute_inside_container,
    _verify_cfw_requalification_image,
)
from builder.pipeline import generate_build_script
from cage.cli import build_parser, cmd_build
from core.manifest import Manifest
from runtime.launcher import build_run_plan
from tests.bundle_fixtures import materialize_runnable_prefix


ROOT = Path(__file__).resolve().parents[1]

APP = {
    "schemaVersion": "cage.app/v0",
    "name": "phase1-app",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "11.0", "network": "none"},
    "launch": {"entrypoint": "C:/Program Files/App/App.exe"},
    "provenance": {"sources": []},
}


def _claim_runnable(bundle: Path) -> None:
    status_path = bundle / "metadata/status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({
        "state": "build-passed",
        "dryRun": False,
        "runnable": True,
        "materializedPrefix": True,
        "hasDefaultLaunch": True,
    })
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")


class CanonicalPrefixScriptTests(unittest.TestCase):
    def test_build_script_atomically_promotes_only_bundle_prefix(self):
        script = generate_build_script(Manifest.from_dict(APP))

        self.assertNotIn("/opt/cage/rootfs", script)
        self.assertIn("/opt/cage/prefix.partial", script)
        self.assertIn("/opt/cage/prefix", script)
        self.assertIn("CAGE_PREFIX_PARTIAL", script)
        self.assertIn('rm -f "$WINEPREFIX/dosdevices/z:"', script)
        self.assertLess(script.index('rm -f "$WINEPREFIX/dosdevices/z:"'), script.index('cp -a "$WINEPREFIX/." "$CAGE_PREFIX_PARTIAL/"'))
        self.assertIn("mv \"$CAGE_PREFIX_PARTIAL\" \"$CAGE_PREFIX_FINAL\"", script)
        self.assertLess(script.index("Verifying launch executable"), script.index("mv \"$CAGE_PREFIX_PARTIAL\""))

    def test_seeded_prefix_skips_producer_owned_wineboot_lifecycle(self):
        data = {
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": []}}],
        }
        script = generate_build_script(Manifest.from_dict(data))

        self.assertIn('Phase 1: Adopting prepared Wine prefix', script)
        self.assertIn('Prepared prefix adopted; skipping producer-owned wineboot lifecycle', script)
        self.assertNotIn('wine wineboot -u', script)
        self.assertNotIn('wine wineboot --init', script)

    def test_unseeded_prefix_runs_wineboot_init_and_retains_its_failure_boundary(self):
        script = generate_build_script(Manifest.from_dict(APP))

        self.assertIn('wineboot_log="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/wineboot.log"', script)
        self.assertIn('wineboot_rc="$?"', script)
        self.assertIn('wine wineboot --init', script)
        self.assertIn('wineboot --init failed with exit code $wineboot_rc', script)

    def test_launch_values_are_shell_quoted_in_generated_script(self):
        data = dict(APP)
        data["launch"] = {
            "entrypoint": "C:/Program Files/App/$(touch /tmp/cage-injected).exe",
            "args": ["$(touch /tmp/cage-args-injected)"],
        }

        script = generate_build_script(Manifest.from_dict(data))

        self.assertNotIn('echo "C:/Program Files/App/$(touch', script)
        self.assertNotIn('echo "  Args: $(touch', script)
        self.assertIn("'C:/Program Files/App/$(touch /tmp/cage-injected).exe'", script)
        self.assertIn("'$(touch /tmp/cage-args-injected)'", script)


class PrefixRunnabilityTests(unittest.TestCase):
    def test_requested_chocolatey_packages_require_valid_evidence(self):
        data = {
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            status_path = bundle / "metadata/status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["state"] = "build-passed"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            result = verify_bundle(bundle)
        check = next(check for check in result["checks"] if check["id"] == "chocolatey-package-evidence")
        self.assertFalse(check["ok"])
        self.assertIn("missing", check["message"])

    def test_package_free_chocolatey_bundle_does_not_require_evidence(self):
        data = {**APP, "modules": [{"type": "chocolatey", "install": {"packages": []}}]}
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            result = verify_bundle(bundle)
        check = next(check for check in result["checks"] if check["id"] == "chocolatey-package-evidence")
        self.assertTrue(check["ok"])

    def test_valid_requested_chocolatey_evidence_is_accepted(self):
        data = {**APP, "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}]}
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            package_dir = bundle / "prefix/drive_c/ProgramData/chocolatey/lib/7zip"
            package_dir.mkdir(parents=True)
            nuspec = package_dir / "7zip.nuspec"
            nupkg = package_dir / "7zip.24.09.nupkg"
            nuspec.write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            nupkg.write_bytes(b"exact package bytes")
            status_path = bundle / "metadata/status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["state"] = "build-passed"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            evidence_path = bundle / "metadata/chocolatey-package-evidence.json"
            evidence_path.write_text(json.dumps({
                "schemaVersion": "cage.chocolatey-package-evidence/v0",
                "status": "passed",
                "authority": "host-resolved-public-feed-receipt",
                "sourceUrl": "https://community.chocolatey.org/api/v2/",
                "requested": [{
                    "id": "7zip",
                    "observed": True,
                    "version": "24.09",
                    "authority": "host-resolved-public-feed-receipt",
                    "feedReceipt": {
                        "version": "24.09",
                        "packageHashAlgorithm": "SHA512",
                        "packageHash": hashlib.sha512(nupkg.read_bytes()).hexdigest(),
                    },
                    "nuspecPath": "7zip/7zip.nuspec",
                    "nuspecSha256": hashlib.sha256(nuspec.read_bytes()).hexdigest(),
                    "nupkgPath": "7zip/7zip.24.09.nupkg",
                    "nupkgSha256": hashlib.sha256(nupkg.read_bytes()).hexdigest(),
                }],
                "checks": {"requestedPackages": True},
                "returnCodes": {"install": 0, "settle": 0, "query": 0},
            }), encoding="utf-8")
            result = verify_bundle(bundle)
            self.assertTrue(evidence_path.exists())
            outside = Path(tmp) / "outside-valid-evidence.json"
            outside.write_bytes(evidence_path.read_bytes())
            evidence_path.unlink()
            evidence_path.symlink_to(outside)
            symlink_result = verify_bundle(bundle)
        check = next(check for check in result["checks"] if check["id"] == "chocolatey-package-evidence")
        self.assertTrue(check["ok"])
        symlink_check = next(
            check for check in symlink_result["checks"] if check["id"] == "chocolatey-package-evidence"
        )
        self.assertFalse(symlink_check["ok"])

    def test_symlinked_chocolatey_evidence_is_rejected(self):
        data = {**APP, "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}]}
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            status_path = bundle / "metadata/status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["state"] = "build-passed"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            outside = Path(tmp) / "outside-evidence.json"
            outside.write_text("{}", encoding="utf-8")
            (bundle / "metadata/chocolatey-package-evidence.json").symlink_to(outside)

            result = verify_bundle(bundle)

        check = next(check for check in result["checks"] if check["id"] == "chocolatey-package-evidence")
        self.assertFalse(check["ok"])

    def test_malformed_requested_chocolatey_evidence_fails_closed(self):
        data = {**APP, "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}]}
        malformed = (
            [],
            {"requested": ["not-an-object"]},
            {
                "schemaVersion": "cage.chocolatey-package-evidence/v0",
                "status": "passed",
                "requested": [{"id": "7zip", "observed": True, "version": "   "}],
                "checks": {"requestedPackages": True},
                "returnCodes": {"install": False, "settle": 0, "query": 0},
            },
        )
        for evidence in malformed:
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as tmp:
                bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
                status_path = bundle / "metadata/status.json"
                status = json.loads(status_path.read_text(encoding="utf-8"))
                status["state"] = "build-passed"
                status_path.write_text(json.dumps(status), encoding="utf-8")
                (bundle / "metadata/chocolatey-package-evidence.json").write_text(
                    json.dumps(evidence), encoding="utf-8"
                )

                result = verify_bundle(bundle)

                check = next(item for item in result["checks"] if item["id"] == "chocolatey-package-evidence")
                self.assertFalse(check["ok"])

    def test_chocolatey_evidence_hashes_exact_package_bytes(self):
        data = {**APP, "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}]}
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            package_dir = bundle / "prefix/drive_c/ProgramData/chocolatey/lib/7zip"
            package_dir.mkdir(parents=True)
            nuspec = package_dir / "7zip.nuspec"
            nupkg = package_dir / "7zip.24.09.nupkg"
            nuspec.write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            nupkg.write_bytes(b"trusted bytes")
            evidence = {
                "schemaVersion": "cage.chocolatey-package-evidence/v0",
                "status": "passed",
                "authority": "host-resolved-public-feed-receipt",
                "sourceUrl": "https://community.chocolatey.org/api/v2/",
                "requested": [{
                    "id": "7zip", "observed": True, "version": "24.09",
                    "authority": "host-resolved-public-feed-receipt",
                    "feedReceipt": {
                        "version": "24.09",
                        "packageHashAlgorithm": "SHA512",
                        "packageHash": hashlib.sha512(nupkg.read_bytes()).hexdigest(),
                    },
                    "nuspecPath": "7zip/7zip.nuspec",
                    "nuspecSha256": hashlib.sha256(nuspec.read_bytes()).hexdigest(),
                    "nupkgPath": "7zip/7zip.24.09.nupkg",
                    "nupkgSha256": hashlib.sha256(nupkg.read_bytes()).hexdigest(),
                }],
                "checks": {"requestedPackages": True},
                "returnCodes": {"install": 0, "settle": 0, "query": 0},
            }
            status_path = bundle / "metadata/status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["state"] = "build-passed"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            evidence_path = bundle / "metadata/chocolatey-package-evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            self.assertTrue(next(
                check for check in verify_bundle(bundle)["checks"]
                if check["id"] == "chocolatey-package-evidence"
            )["ok"])
            evidence["requested"][0]["version"] = "attacker-claimed"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            self.assertFalse(next(
                check for check in verify_bundle(bundle)["checks"]
                if check["id"] == "chocolatey-package-evidence"
            )["ok"])
            evidence["requested"][0]["version"] = "24.09"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            nupkg.write_bytes(b"tampered bytes")
            self.assertFalse(next(
                check for check in verify_bundle(bundle)["checks"]
                if check["id"] == "chocolatey-package-evidence"
            )["ok"])

    def test_placeholder_prefix_cannot_be_marked_runnable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            _claim_runnable(bundle)

            result = verify_bundle(bundle)

        self.assertTrue(result["valid"])
        self.assertFalse(result["runnable"])
        self.assertIn("prefix-materialization", {check["id"] for check in result["runnabilityChecks"]})

    def test_missing_launch_executable_prevents_runnable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)
            (bundle / "prefix/drive_c/.keep").unlink()
            (bundle / "prefix/drive_c/windows").mkdir()
            (bundle / "prefix/drive_c/windows/system.reg").write_text("baseline", encoding="utf-8")
            (bundle / "metadata/prefix-materialization.json").write_text(
                json.dumps({
                    "schemaVersion": "cage.prefix-materialization/v0",
                    "completed": True,
                    "fileCount": 1,
                    "byteSize": 8,
                }),
                encoding="utf-8",
            )
            _claim_runnable(bundle)

            result = verify_bundle(bundle)

        self.assertTrue(result["valid"])
        self.assertFalse(result["runnable"])
        launch_check = next(check for check in result["runnabilityChecks"] if check["id"] == "launch-executable")
        self.assertFalse(launch_check["ok"])


class ExecutorVerificationTests(unittest.TestCase):
    @staticmethod
    def _receipt_for(package_dir: Path, version: str = "24.09") -> dict[str, str]:
        nupkg = next(package_dir.glob("*.nupkg"))
        return {
            "version": version,
            "packageHashAlgorithm": "SHA512",
            "packageHash": hashlib.sha512(nupkg.read_bytes()).hexdigest(),
        }

    def test_public_feed_receipt_parser_requires_sha512_and_one_entry(self):
        digest = hashlib.sha512(b"package bytes").digest()
        payload = (
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
            '<entry><title>7zip</title><content><m:properties xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
            '<d:Version>24.09</d:Version>'
            f'<d:PackageHash>{base64.b64encode(digest).decode()}</d:PackageHash>'
            '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>'
            '<d:IsLatestVersion>true</d:IsLatestVersion>'
            '</m:properties></content></entry></feed>'
        ).encode()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = payload
        with patch("builder.executor.urllib.request.urlopen", side_effect=[response, AssertionError("fallback should not run")]):
            receipt = _resolve_public_chocolatey_package_receipt(
                "https://community.chocolatey.org/api/v2/", "7zip"
            )
        self.assertEqual(receipt, {
            "version": "24.09",
            "packageHashAlgorithm": "SHA512",
            "packageHash": digest.hex(),
        })

    def test_public_feed_receipt_resolves_observed_version_without_latest_requirement(self):
        digest = hashlib.sha512(b"package bytes").digest()
        payload = (
            '<entry xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
            '<title>notepadplusplus</title><content>'
            '<m:properties xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
            '<d:Version>8.9.7</d:Version>'
            f'<d:PackageHash>{base64.b64encode(digest).decode()}</d:PackageHash>'
            '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>'
            '<d:IsLatestVersion>false</d:IsLatestVersion>'
            '</m:properties></content></entry>'
        ).encode()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = payload
        with patch("builder.executor.urllib.request.urlopen", return_value=response) as urlopen:
            receipt = _resolve_public_chocolatey_package_receipt(
                "https://community.chocolatey.org/api/v2/", "notepadplusplus", "8.9.7"
            )

        self.assertEqual(receipt, {
            "version": "8.9.7",
            "packageHashAlgorithm": "SHA512",
            "packageHash": digest.hex(),
        })
        requested_url = urlopen.call_args.args[0].full_url
        self.assertIn("Packages(Id='notepadplusplus',Version='8.9.7')", requested_url)
        self.assertNotIn("IsLatestVersion", requested_url)

        wrong_namespace = payload.replace(
            b'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"',
            b'xmlns:d="urn:attacker-controlled"',
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = wrong_namespace
        with patch("builder.executor.urllib.request.urlopen", return_value=response):
            self.assertIsNone(_resolve_public_chocolatey_package_receipt(
                "https://community.chocolatey.org/api/v2/", "notepadplusplus", "8.9.7"
            ))

    def test_public_feed_receipt_rejects_duplicate_exact_authority_fields(self):
        digest = hashlib.sha512(b"package bytes").digest()
        payload = (
            '<entry xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
            'xmlns:x="urn:attacker-controlled">'
            '<title>notepadplusplus</title><content>'
            '<m:properties xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
            '<d:Version>8.9.7</d:Version>'
            f'<d:PackageHash>{base64.b64encode(digest).decode()}</d:PackageHash>'
            '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>'
            '</m:properties></content></entry>'
        )
        cases = {
            "duplicate Atom title": payload.replace(
                '<title>notepadplusplus</title>',
                '<title>notepadplusplus</title><title>wrong</title>',
            ),
            "cross-namespace title": payload.replace(
                '<title>notepadplusplus</title>',
                '<title>notepadplusplus</title><x:title>wrong</x:title>',
            ),
            "duplicate Version": payload.replace(
                '<d:Version>8.9.7</d:Version>',
                '<d:Version>8.9.7</d:Version><d:Version>0.0.0</d:Version>',
            ),
            "cross-namespace Version": payload.replace(
                '<d:Version>8.9.7</d:Version>',
                '<d:Version>8.9.7</d:Version><x:Version>0.0.0</x:Version>',
            ),
            "duplicate PackageHash": payload.replace(
                '</d:PackageHash>',
                '</d:PackageHash><d:PackageHash>AAAA</d:PackageHash>',
            ),
            "cross-namespace PackageHash": payload.replace(
                '</d:PackageHash>',
                '</d:PackageHash><x:PackageHash>AAAA</x:PackageHash>',
            ),
            "duplicate PackageHashAlgorithm": payload.replace(
                '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>',
                '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>'
                '<d:PackageHashAlgorithm>SHA256</d:PackageHashAlgorithm>',
            ),
            "cross-namespace PackageHashAlgorithm": payload.replace(
                '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>',
                '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>'
                '<x:PackageHashAlgorithm>SHA256</x:PackageHashAlgorithm>',
            ),
        }
        for name, response_payload in cases.items():
            response = MagicMock()
            response.__enter__.return_value.read.return_value = response_payload.encode()
            with self.subTest(name=name), patch(
                "builder.executor.urllib.request.urlopen", return_value=response
            ) as urlopen:
                self.assertIsNone(_resolve_public_chocolatey_package_receipt(
                    "https://community.chocolatey.org/api/v2/",
                    "notepadplusplus",
                    "8.9.7",
                ))
                self.assertEqual(urlopen.call_count, 1)

    def test_public_feed_receipt_rejects_missing_or_mismatched_observed_version(self):
        empty = MagicMock()
        empty.__enter__.return_value.read.return_value = b'<feed xmlns="http://www.w3.org/2005/Atom" />'
        with patch("builder.executor.urllib.request.urlopen", return_value=empty) as urlopen:
            self.assertIsNone(_resolve_public_chocolatey_package_receipt(
                "https://community.chocolatey.org/api/v2/", "notepadplusplus", "8.9.7"
            ))
        self.assertEqual(urlopen.call_count, 1)
        for version in (
            "", "8.9.7' or true", "1.2.3%27", "1.2.3/evil",
            "1.2.3?x=y", "1.2.3#fragment", "1.2.3\\evil", "1.2.3\tbad",
        ):
            with self.subTest(version=version), patch("builder.executor.urllib.request.urlopen") as blocked:
                self.assertIsNone(_resolve_public_chocolatey_package_receipt(
                    "https://community.chocolatey.org/api/v2/", "notepadplusplus", version
                ))
                blocked.assert_not_called()

    def test_public_feed_receipt_uses_search_fallback_only_for_valid_empty_primary(self):
        digest = hashlib.sha512(b"package bytes").digest()
        empty_primary = MagicMock()
        empty_primary.__enter__.return_value.read.return_value = b'<feed xmlns="http://www.w3.org/2005/Atom" />'
        fallback_payload = (
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
            '<entry><title>7zip</title><content><m:properties xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
            '<d:Version>24.09</d:Version>'
            f'<d:PackageHash>{base64.b64encode(digest).decode()}</d:PackageHash>'
            '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>'
            '<d:IsLatestVersion>true</d:IsLatestVersion>'
            '</m:properties></content></entry></feed>'
        ).encode()
        fallback = MagicMock()
        fallback.__enter__.return_value.read.return_value = fallback_payload
        with patch("builder.executor.urllib.request.urlopen", side_effect=[empty_primary, fallback]) as urlopen:
            receipt = _resolve_public_chocolatey_package_receipt(
                "https://community.chocolatey.org/api/v2/", "7zip"
            )

        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["version"], "24.09")
        self.assertEqual(urlopen.call_count, 2)

    def test_public_feed_receipt_rejects_nonlatest_primary_entry(self):
        digest = hashlib.sha512(b"package bytes").digest()

        def payload(is_latest: bool) -> bytes:
            return (
                '<feed xmlns="http://www.w3.org/2005/Atom" '
                'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
                '<entry><title>7zip</title><content><m:properties xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
                '<d:Version>24.09</d:Version>'
                f'<d:PackageHash>{base64.b64encode(digest).decode()}</d:PackageHash>'
                '<d:PackageHashAlgorithm>SHA512</d:PackageHashAlgorithm>'
                f'<d:IsLatestVersion>{str(is_latest).lower()}</d:IsLatestVersion>'
                '</m:properties></content></entry></feed>'
            ).encode()

        primary = MagicMock()
        primary.__enter__.return_value.read.return_value = payload(False)
        with patch("builder.executor.urllib.request.urlopen", return_value=primary) as urlopen:
            receipt = _resolve_public_chocolatey_package_receipt(
                "https://community.chocolatey.org/api/v2/", "7zip"
            )

        self.assertIsNone(receipt)
        self.assertEqual(urlopen.call_count, 1)

    def test_public_feed_receipt_rejects_malformed_primary_without_fallback(self):
        primary = MagicMock()
        primary.__enter__.return_value.read.return_value = b"<not-xml"
        fallback = MagicMock()
        with patch("builder.executor.urllib.request.urlopen", side_effect=[primary, fallback]) as urlopen:
            receipt = _resolve_public_chocolatey_package_receipt(
                "https://community.chocolatey.org/api/v2/", "7zip"
            )

        self.assertIsNone(receipt)
        self.assertEqual(urlopen.call_count, 1)

    def test_public_feed_receipt_rejects_structurally_invalid_primary_responses(self):
        valid_fallback = MagicMock()
        valid_fallback.__enter__.return_value.read.return_value = (
            b'<feed xmlns="http://www.w3.org/2005/Atom" />'
        )
        cases = (
            b"<root />",
            b'<feed xmlns="urn:not-atom" />',
            b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>wrong-id</title></entry></feed>',
        )
        for primary_payload in cases:
            with self.subTest(primary_payload=primary_payload):
                primary = MagicMock()
                primary.__enter__.return_value.read.return_value = primary_payload
                with patch("builder.executor.urllib.request.urlopen", side_effect=[primary, valid_fallback]) as urlopen:
                    receipt = _resolve_public_chocolatey_package_receipt(
                        "https://community.chocolatey.org/api/v2/", "7zip"
                    )
                self.assertIsNone(receipt)
                self.assertEqual(urlopen.call_count, 1)

    def test_host_rewrites_chocolatey_evidence_from_exported_package_bytes(self):
        manifest = Manifest.from_dict({
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=False)
            package_dir = bundle / "prefix/drive_c/ProgramData/chocolatey/lib/7zip"
            package_dir.mkdir(parents=True)
            (package_dir / "7zip.nuspec").write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            nupkg = package_dir / "7zip.24.09.nupkg"
            nupkg.write_bytes(b"exported package bytes")
            evidence_path = bundle / "metadata/chocolatey-package-evidence.json"
            evidence_path.write_text('{"status":"attacker-claimed"}', encoding="utf-8")

            receipt = self._receipt_for(package_dir)
            with patch("builder.executor._resolve_public_chocolatey_package_receipt", return_value=receipt) as resolver:
                self.assertTrue(_write_host_chocolatey_package_evidence(manifest, bundle))
            resolver.assert_called_once_with(
                "https://community.chocolatey.org/api/v2/", "7zip", "24.09"
            )
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["authority"], "host-resolved-public-feed-receipt")
        self.assertEqual(evidence["requested"][0]["feedReceipt"], receipt)
        self.assertEqual(evidence["requested"][0]["authority"], "host-resolved-public-feed-receipt")
        self.assertEqual(evidence["requested"][0]["version"], "24.09")
        self.assertEqual(
            evidence["requested"][0]["nupkgSha256"],
            hashlib.sha256(b"exported package bytes").hexdigest(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=False)
            package_dir = bundle / "prefix/drive_c/ProgramData/chocolatey/lib/7zip"
            package_dir.mkdir(parents=True)
            (package_dir / "7zip.nuspec").write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            (package_dir / "7zip.24.09.nupkg").write_bytes(b"exported package bytes")
            with patch("builder.executor._resolve_public_chocolatey_package_receipt", return_value={
                "version": "attacker-claimed",
                "packageHashAlgorithm": "SHA512",
                "packageHash": hashlib.sha512(b"exported package bytes").hexdigest(),
            }):
                self.assertFalse(_write_host_chocolatey_package_evidence(manifest, bundle))

    def test_host_rejects_bundle_reached_through_symlinked_parent(self):
        manifest = Manifest.from_dict({
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            bundle = create_bundle(manifest, real_parent, dry_run=False)
            package_dir = bundle / "prefix/drive_c/ProgramData/chocolatey/lib/7zip"
            package_dir.mkdir(parents=True)
            (package_dir / "7zip.nuspec").write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            (package_dir / "7zip.24.09.nupkg").write_bytes(b"exported package bytes")
            alias_parent = root / "alias-parent"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            alias_bundle = alias_parent / bundle.name

            with patch("builder.executor._resolve_public_chocolatey_package_receipt", return_value=self._receipt_for(package_dir)):
                self.assertFalse(_write_host_chocolatey_package_evidence(manifest, alias_bundle))
            self.assertFalse(verify_bundle(alias_bundle)["valid"])

    def test_host_rejects_symlinked_package_tree_before_feed_resolution(self):
        manifest = Manifest.from_dict({
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = create_bundle(manifest, root, dry_run=False)
            lib = bundle / "prefix/drive_c/ProgramData/chocolatey/lib"
            lib.mkdir(parents=True)
            outside = root / "outside-package"
            outside.mkdir()
            (outside / "7zip.nuspec").write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            (outside / "7zip.24.09.nupkg").write_bytes(b"outside bytes")
            (lib / "7zip").symlink_to(outside, target_is_directory=True)

            with patch("builder.executor._resolve_public_chocolatey_package_receipt") as resolver:
                self.assertFalse(_write_host_chocolatey_package_evidence(manifest, bundle))
            resolver.assert_not_called()

    def test_host_rejects_symlinked_evidence_output(self):
        manifest = Manifest.from_dict({
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=False)
            package_dir = bundle / "prefix/drive_c/ProgramData/chocolatey/lib/7zip"
            package_dir.mkdir(parents=True)
            (package_dir / "7zip.nuspec").write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            (package_dir / "7zip.24.09.nupkg").write_bytes(b"exported package bytes")
            outside = Path(tmp) / "outside-evidence.json"
            evidence_path = bundle / "metadata/chocolatey-package-evidence.json"
            evidence_path.symlink_to(outside)

            with patch("builder.executor._resolve_public_chocolatey_package_receipt", return_value=self._receipt_for(package_dir)):
                self.assertFalse(_write_host_chocolatey_package_evidence(manifest, bundle))
            self.assertFalse(outside.exists())

    def test_host_rejects_symlinked_chocolatey_lib_root(self):
        manifest = Manifest.from_dict({
            **APP,
            "modules": [{"type": "chocolatey", "install": {"packages": ["7zip"]}}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=False)
            nominal_lib = bundle / "prefix/drive_c/ProgramData/chocolatey/lib"
            nominal_lib.parent.mkdir(parents=True, exist_ok=True)
            outside = Path(tmp) / "outside-lib"
            package_dir = outside / "7zip"
            package_dir.mkdir(parents=True)
            (package_dir / "7zip.nuspec").write_text(
                "<package><metadata><id>7zip</id><version>24.09</version></metadata></package>",
                encoding="utf-8",
            )
            (package_dir / "7zip.24.09.nupkg").write_bytes(b"outside package bytes")
            nominal_lib.symlink_to(outside, target_is_directory=True)

            with patch("builder.executor._resolve_public_chocolatey_package_receipt", return_value=self._receipt_for(package_dir)):
                self.assertFalse(_write_host_chocolatey_package_evidence(manifest, bundle))

    def test_container_success_fails_when_host_cannot_bind_package_bytes(self):
        qualified = {
            **json.loads((ROOT / "core/chocolatey/assets/cfw-runtime-v1.0.4-wine-11.0.json").read_text()),
            "sessionContract": "cage.selkies-wayland/v1",
        }
        manifest = Manifest.from_dict({
            **APP,
            "modules": [{
                "type": "chocolatey",
                "install": {"packages": ["7zip"], "runtimeArtifact": qualified},
            }],
        })
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=False)

            class Completed:
                returncode = 0
                stdout = "container claimed success"
                stderr = ""

            def fake_run(*_args, **_kwargs):
                materialize_runnable_prefix(bundle, entrypoint=APP["launch"]["entrypoint"])
                return Completed()

            with patch("builder.executor._resolve_public_chocolatey_package_receipt", return_value=None), patch("builder.executor._run_container_command", side_effect=fake_run), patch("sys.stderr", io.StringIO()):
                result = execute_inside_container(
                    manifest, bundle, engine="docker",
                    timeout=5, workspace=tmp,
                )

        self.assertFalse(result.success)
        self.assertFalse(result.runnable)
        self.assertIn("host failed to bind", result.error or "")

    def test_container_exit_zero_without_materialized_prefix_fails_verification(self):
        manifest = Manifest.from_dict(APP)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(manifest, Path(tmp), dry_run=False)

            class Completed:
                returncode = 0
                stdout = "container exited zero without exporting a prefix"
                stderr = ""

            with patch("builder.executor._run_container_command", return_value=Completed()), patch("sys.stderr", io.StringIO()):
                result = execute_inside_container(
                    manifest,
                    bundle,
                    engine="docker",
                    image_ref="local/runtime:test",
                    timeout=5,
                    workspace=tmp,
                )

            status = json.loads((bundle / "metadata/status.json").read_text(encoding="utf-8"))

        self.assertFalse(result.success)
        self.assertEqual(status["state"], "verification-failed")
        self.assertFalse(status["runnable"])
        self.assertIn("materialized prefix", result.error or "")


class OCIExportGateTests(unittest.TestCase):
    def test_oci_export_rejects_structurally_valid_non_runnable_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)

            with self.assertRaisesRegex(OCIExportError, "not runnable"):
                create_oci_export_plan(bundle, tag="phase1-app:test")


class BuildSourcePreflightTests(unittest.TestCase):
    def test_cfw_launch_cannot_override_producer_environment(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        runtime = {
            "id": "cfw-runtime-test",
            "url": "https://example.invalid/runtime.tar.gz",
            "evidenceUrl": "https://example.invalid/runtime.json",
            "manifestUrl": "https://example.invalid/manifest.json",
            "manifestSha256": "c" * 64,
            "wineImage": image,
            "wineVersions": ["wine-11.0"],
            "environment": {"WINEDLLOVERRIDES": ""},
        }
        data = {
            **APP,
            "launch": {
                **APP["launch"],
                "env": {"WINEDLLOVERRIDES": "mscoree=n"},
            },
            "modules": [{
                "type": "chocolatey",
                "install": {"packages": [], "runtimeArtifact": runtime},
            }],
        }
        with self.assertRaisesRegex(Exception, "producer-owned environment"):
            Manifest.from_dict(data)

    def test_cfw_build_uses_pinned_image_for_execution_graph_and_oci_base(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        data = {
            **APP,
            "modules": [{"type": "chocolatey", "install": {
                "packages": [],
                "runtimeArtifact": {
                    "id": "cfw-runtime-test",
                    "url": "https://example.invalid/runtime.tar.gz",
                    "evidenceUrl": "https://example.invalid/runtime.json",
                    "manifestUrl": "https://example.invalid/manifest.json",
                    "manifestSha256": "c" * 64,
                    "wineImage": image,
                    "wineVersions": ["wine-11.0"], "environment": {"WINEDLLOVERRIDES": ""},
                },
            }}],
        }
        manifest = Manifest.from_dict(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "dist"
            args = build_parser().parse_args([
                "build", str(root / "recipe.cage.yaml"),
                "--output", str(output), "--workspace", str(root), "--engine", "docker",
            ])
            failed = BuildResult(
                success=False,
                bundle_path=str(output / "phase1-app-1.0.0"),
                runtime_provider="wine",
                runtime_version="11.0",
                image_ref=image,
                engine="docker",
                exit_code=1,
            )
            with patch("cage.cli.load_manifest", return_value=manifest), \
                 patch("cage.cli.execute_inside_container", return_value=failed) as execute, \
                 patch("cage.cli.build_oci_image", return_value={"outputTag": "phase1-app:test"}) as oci, \
                 patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                rc = cmd_build(args)
            bundle = output / "phase1-app-1.0.0"
            graph = json.loads((bundle / "metadata/graph.json").read_text(encoding="utf-8"))
            runtime = json.loads((bundle / "runtime/runtime.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 1)
        self.assertEqual(execute.call_args.kwargs["image_ref"], image)
        self.assertEqual(oci.call_args.args[1], image)
        self.assertEqual(graph["builderRuntime"]["image"], image)
        self.assertEqual(graph["runnerRuntime"]["image"], image)
        self.assertEqual(graph["builderRuntime"]["environment"], {"WINEDLLOVERRIDES": ""})
        self.assertEqual(graph["runnerRuntime"]["environment"], {"WINEDLLOVERRIDES": ""})
        self.assertEqual(runtime["ociImage"], image)
        self.assertEqual(runtime["environment"], {"WINEDLLOVERRIDES": ""})

    def test_cfw_environment_reaches_run_plan_and_oci_export(self):
        image = "ghcr.io/pelagians/cage-wine@sha256:" + "d" * 64
        data = {
            **APP,
            "modules": [{"type": "chocolatey", "install": {
                "packages": [],
                "runtimeArtifact": {
                    "id": "cfw-runtime-test",
                    "url": "https://example.invalid/runtime.tar.gz",
                    "evidenceUrl": "https://example.invalid/runtime.json",
                    "manifestUrl": "https://example.invalid/manifest.json",
                    "manifestSha256": "c" * 64,
                    "wineImage": image,
                    "wineVersions": ["wine-11.0"],
                    "environment": {"WINEDLLOVERRIDES": ""},
                    "sessionContract": "cage.selkies-wayland/v1",
                },
            }}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=False)
            materialize_runnable_prefix(
                bundle,
                entrypoint=APP["launch"]["entrypoint"],
                chocolatey=True,
            )
            run_plan = build_run_plan(bundle, engine="podman")
            oci_plan = create_oci_export_plan(bundle, tag="phase1-app:test")

        self.assertEqual(run_plan["container"]["environment"]["WINEDLLOVERRIDES"], "")
        self.assertIn("WINEDLLOVERRIDES=", run_plan["container"]["argv"])
        self.assertEqual(oci_plan["runtime"]["environment"], {"WINEDLLOVERRIDES": ""})
        self.assertIn('ENV WINEDLLOVERRIDES=""', oci_plan["containerfile"]["content"])

    def test_failed_source_preflight_writes_evidence_and_skips_container(self):
        data = dict(APP)
        data["modules"] = [{
            "type": "portable",
            "source": "inputs/missing-app.zip",
            "target": "C:/Program Files/App",
        }]
        manifest = Manifest.from_dict(data)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "dist"
            args = build_parser().parse_args([
                "build",
                str(root / "recipe.cage.yaml"),
                "--output",
                str(output),
                "--workspace",
                str(root),
                "--engine",
                "docker",
            ])
            with patch("cage.cli.load_manifest", return_value=manifest), \
                 patch("cage.cli.execute_inside_container") as execute, \
                 patch("sys.stdout", io.StringIO()), \
                 patch("sys.stderr", io.StringIO()):
                rc = cmd_build(args)

            bundle = output / "phase1-app-1.0.0"
            integrity = json.loads((bundle / "metadata/source-integrity.json").read_text(encoding="utf-8"))
            policy = json.loads((bundle / "metadata/source-policy.json").read_text(encoding="utf-8"))
            status = json.loads((bundle / "metadata/status.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 1)
        execute.assert_not_called()
        self.assertFalse(integrity["valid"])
        self.assertFalse(policy["valid"])
        self.assertEqual(status["state"], "source-failed")
        self.assertFalse(status["runnable"])


if __name__ == "__main__":
    unittest.main()


class CfwRequalificationTests(unittest.TestCase):
    def test_candidate_requires_universal_init_and_contract_label(self):
        class Completed:
            returncode = 0
            stdout = '["/init"]\ncage.selkies-wayland/v1\n'
            stderr = ""

        with patch("builder.executor.subprocess.run", return_value=Completed()):
            identity = _verify_cfw_requalification_image("docker", "cage-wine-cfw-candidate:test")
        self.assertEqual(identity["entrypoint"], ["/init"])
        self.assertEqual(identity["sessionContract"], "cage.selkies-wayland/v1")

    def test_executor_binds_prepared_prefix_to_producer_while_running_candidate(self):
        source = (ROOT / "builder/executor.py").read_text(encoding="utf-8")
        self.assertIn('environment["CAGE_CFW_PRODUCER_IMAGE"] = required_cfw_image', source)

    def test_candidate_rejects_missing_universal_contract(self):
        class Completed:
            returncode = 0
            stdout = '["/init"]\n\n'
            stderr = ""

        with patch("builder.executor.subprocess.run", return_value=Completed()):
            with self.assertRaisesRegex(RuntimeError, "session contract"):
                _verify_cfw_requalification_image("docker", "candidate:test")


class CfwRequalificationCliTests(unittest.TestCase):
    def test_build_parser_separates_candidate_runtime_from_output_image_tag(self):
        args = build_parser().parse_args([
            "build",
            "recipe.cage.yaml",
            "--runtime-image",
            "cage-wine-cfw-candidate:test",
            "--image-tag",
            "application:test",
            "--requalify-cfw-runtime",
        ])
        self.assertEqual(args.runtime_image, "cage-wine-cfw-candidate:test")
        self.assertEqual(args.image_tag, "application:test")
        self.assertTrue(args.requalify_cfw_runtime)
