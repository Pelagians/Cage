"""Tests for Phase 5E OCI push digest recording and image verification."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact.bundle import create_bundle
from artifact.oci import (
    ARTIFACT_IMAGE_SCHEMA_VERSION,
    OCI_IMAGE_VERIFICATION_SCHEMA_VERSION,
    export_oci_image,
    verify_oci_image_metadata,
)
from core.manifest import Manifest

APP = {
    "schemaVersion": "cage.app/v0",
    "name": "verify-demo",
    "version": "2.0.0",
    "runtime": {"provider": "wine", "version": "latest"},
    "dependencies": [],
    "install": [],
    "launch": {
        "entrypoint": "C:/Program Files/VerifyDemo/demo.exe",
        "workingDirectory": "C:/Program Files/VerifyDemo",
    },
    "state": {"defaultPersistence": "persistent"},
    "exports": [],
    "provenance": {"sources": []},
}

LABELS = {
    "io.cage.schema": ARTIFACT_IMAGE_SCHEMA_VERSION,
    "io.cage.app.name": "verify-demo",
    "io.cage.app.version": "2.0.0",
    "io.cage.runtime.provider": "wine",
    "io.cage.runtime.requestedVersion": "latest",
    "io.cage.runtime.resolvedVersion": "11.0",
    "io.cage.runtime.baseImage": "ghcr.io/pelagians/cage-wine:11.0",
    "io.cage.runner": "winehq-stable",
    "io.cage.launcher": "wine",
}

ARTIFACT = {
    "schemaVersion": ARTIFACT_IMAGE_SCHEMA_VERSION,
    "imageType": "runnable-application-image",
    "application": {"name": "verify-demo", "version": "2.0.0"},
    "runtime": {
        "provider": "wine",
        "requestedVersion": "latest",
        "resolvedVersion": "11.0",
        "baseImage": "ghcr.io/pelagians/cage-wine:11.0",
        "runner": "winehq-stable",
        "launcher": "wine",
    },
}


def _bundle(tmp: str | Path) -> Path:
    return create_bundle(Manifest.from_dict(APP), Path(tmp), dry_run=True)


def _completed(args, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


class OCIImagePushDigestTests(unittest.TestCase):
    def test_export_push_records_repo_digest_from_image_inspect(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _bundle(tmp)
            inspect_payload = json.dumps([
                {
                    "Id": "sha256:local-image-id",
                    "RepoDigests": ["ghcr.io/acme/verify-demo@sha256:abc123"],
                    "Config": {"Labels": LABELS},
                }
            ])
            with patch("artifact.oci.shutil.which", return_value="/usr/bin/docker"), \
                 patch("artifact.oci.subprocess.run") as run:
                run.side_effect = [
                    _completed(["docker", "build"], stdout="built"),
                    _completed(["docker", "push"], stdout="digest: sha256:abc123 size: 1234"),
                    _completed(["docker", "image", "inspect"], stdout=inspect_payload),
                ]

                result = export_oci_image(
                    bundle,
                    tag="ghcr.io/acme/verify-demo:2.0.0",
                    engine="docker",
                    context_dir=Path(tmp) / "context",
                    push=True,
                )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["push"]["success"], True)
        self.assertEqual(result["image"]["digest"], "sha256:abc123")
        self.assertEqual(result["image"]["repoDigests"], ["ghcr.io/acme/verify-demo@sha256:abc123"])
        self.assertEqual(result["image"]["labels"]["io.cage.schema"], ARTIFACT_IMAGE_SCHEMA_VERSION)


class OCIImageVerificationTests(unittest.TestCase):
    def test_verify_oci_image_metadata_compares_labels_to_embedded_artifact_json(self):
        inspect_payload = json.dumps([
            {
                "Id": "sha256:local-image-id",
                "RepoDigests": ["ghcr.io/acme/verify-demo@sha256:abc123"],
                "Config": {"Labels": LABELS},
            }
        ])
        with patch("artifact.oci.shutil.which", return_value="/usr/bin/docker"), \
             patch("artifact.oci.subprocess.run") as run:
            run.side_effect = [
                _completed(["docker", "image", "inspect"], stdout=inspect_payload),
                _completed(["docker", "run"], stdout=json.dumps(ARTIFACT)),
            ]

            result = verify_oci_image_metadata(
                "ghcr.io/acme/verify-demo:2.0.0",
                engine="docker",
            )

        self.assertEqual(result["schemaVersion"], OCI_IMAGE_VERIFICATION_SCHEMA_VERSION)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["image"]["digest"], "sha256:abc123")
        self.assertEqual(result["artifactMetadata"]["schemaVersion"], ARTIFACT_IMAGE_SCHEMA_VERSION)
        self.assertTrue(all(check["ok"] for check in result["checks"]))

    def test_verify_oci_image_metadata_reports_label_mismatch(self):
        bad_labels = dict(LABELS)
        bad_labels["io.cage.runtime.resolvedVersion"] = "10.0"
        inspect_payload = json.dumps([
            {
                "Id": "sha256:local-image-id",
                "RepoDigests": ["ghcr.io/acme/verify-demo@sha256:abc123"],
                "Config": {"Labels": bad_labels},
            }
        ])
        with patch("artifact.oci.shutil.which", return_value="/usr/bin/docker"), \
             patch("artifact.oci.subprocess.run") as run:
            run.side_effect = [
                _completed(["docker", "image", "inspect"], stdout=inspect_payload),
                _completed(["docker", "run"], stdout=json.dumps(ARTIFACT)),
            ]

            result = verify_oci_image_metadata(
                "ghcr.io/acme/verify-demo:2.0.0",
                engine="docker",
            )

        self.assertFalse(result["valid"])
        self.assertIn("label io.cage.runtime.resolvedVersion", "\n".join(result["errors"]))

    def test_cli_image_verify_missing_engine_returns_structured_json(self):
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [
                sys.executable,
                "cmd/cage.py",
                "image",
                "verify",
                "local/verify-demo:2.0.0",
                "--engine",
                "definitely-not-a-container-engine",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schemaVersion"], OCI_IMAGE_VERIFICATION_SCHEMA_VERSION)
        self.assertFalse(payload["valid"])
        self.assertIn("container build engine not found", "\n".join(payload["errors"]))


if __name__ == "__main__":
    unittest.main()
