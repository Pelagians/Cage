"""Chocolatey module backed by a verified CFW prepared-prefix artifact."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import re
import shlex
from typing import Any
from urllib.parse import urlparse

from core.chocolatey import asset_sha256, load_asset, load_asset_bytes, render_asset

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$"
)
_WINE_IMAGE_RE = re.compile(r"^ghcr\.io/pelagians/cage-wine@sha256:[0-9a-f]{64}$")
_RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINE_VERSION_RE = re.compile(r"^wine-[0-9]+(?:\.[0-9]+){1,2}$")
_UNSAFE_SOURCE_RE = re.compile(r"[\x00-\x1f\x7f$`;&|<>]")
DEFAULT_CFW_RUNTIME_PROFILE_ID = "cfw-runtime-v1"
DEFAULT_CFW_RUNTIME_ARTIFACT: dict[str, Any] | None = None
CFW_RUNTIME_PROVIDER = "cfw-chocolatey-runtime"

_FAILURE_DIAGNOSTIC_ASSETS = {
    "verify-chocolatey.sh",
    "feature-policy.sh",
    "smoke-lifecycle.sh",
}
_POST_SEED_STEP_SPECS = (
    ("verify-chocolatey.sh", "Diagnose Chocolatey readiness", "wine-run", 600),
    ("feature-policy.sh", "Verify Chocolatey external-host policy", "wine-run", 360),
    ("smoke-lifecycle.sh", "Prove Chocolatey local package lifecycle", "wine-run", 1800),
    ("install-package.sh", "Install Chocolatey packages", "wine-run", 1800),
)
_RUNTIME_FIELDS = {
    "id",
    "url",
    "evidenceUrl",
    "manifestUrl",
    "manifestSha256",
    "wineImage",
    "wineVersions",
    "environment",
}


def _record_command(runtime: dict[str, Any] | None, asset_hashes: dict[str, str]) -> str:
    payload = {
        "schemaVersion": "cage.chocolatey-runtime/v1",
        "runtime": runtime,
        "runtimeAvailable": runtime is not None,
        "assets": asset_hashes,
        "prefixFoundation": CFW_RUNTIME_PROVIDER,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return (
        "mkdir -p \"${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata\" && "
        "python3 -c 'import json,sys; from pathlib import Path; "
        "p=Path(sys.argv[1]); p.write_text(json.dumps(json.loads(sys.argv[2]), indent=2, sort_keys=True) + \"\\n\", encoding=\"utf-8\")' "
        '"${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-runtime-profile.json" '
        + shlex.quote(encoded)
    )


@dataclass
class ChocolateyModule(ModuleBase):
    """Install packages after seeding one CFW-owned compatibility runtime."""

    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    package_source: str | None = None

    @staticmethod
    def _validate_runtime_source(field_name: str, value: str) -> None:
        if _UNSAFE_SOURCE_RE.search(value):
            raise ModuleError(f"chocolatey runtimeArtifact.{field_name} contains unsafe characters")
        parsed = urlparse(value)
        if parsed.scheme == "https":
            if (
                not parsed.hostname
                or _HOSTNAME_RE.fullmatch(parsed.hostname) is None
                or parsed.username
                or parsed.password
            ):
                raise ModuleError(f"chocolatey runtimeArtifact.{field_name} must be a plain HTTPS URL")
            return
        if parsed.scheme == "file":
            if parsed.netloc not in ("", "localhost") or not parsed.path.startswith("/"):
                raise ModuleError(f"chocolatey runtimeArtifact.{field_name} must use an absolute file URL")
            return
        if not value.startswith("/"):
            raise ModuleError(
                f"chocolatey runtimeArtifact.{field_name} must use https://, file://, or an absolute path"
            )

    def validate(self) -> None:
        self._packages()
        self._runtime_artifact()
        if self.package_source:
            if _UNSAFE_SOURCE_RE.search(self.package_source):
                raise ModuleError("chocolatey packageSource contains unsafe characters")
            parsed = urlparse(self.package_source)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or _HOSTNAME_RE.fullmatch(parsed.hostname) is None
                or parsed.username
                or parsed.password
            ):
                raise ModuleError("chocolatey packageSource must be a plain HTTPS URL")

    def capabilities(self) -> dict[str, str]:
        return {
            "package-manager": "chocolatey",
            "prefix-foundation": "cfw-prepared-runtime",
        }

    def _packages(self) -> list[str]:
        if not isinstance(self.install, dict):
            raise ModuleError("chocolatey module requires 'install' object")
        packages = self.install.get("packages")
        if not isinstance(packages, list):
            raise ModuleError("chocolatey module 'install.packages' must be a list")
        if not all(isinstance(package, str) and package for package in packages):
            raise ModuleError("chocolatey module 'install.packages' must be a list of non-empty strings")
        for package in packages:
            if not _PACKAGE_RE.fullmatch(package):
                raise ModuleError(
                    "chocolatey package names must begin with a letter or number and use "
                    "letters, numbers, dots, underscores, plus, or dashes only: "
                    f"{package}"
                )
        return packages

    def _runtime_artifact(self) -> dict[str, Any] | None:
        if not isinstance(self.install, dict):
            raise ModuleError("chocolatey module requires 'install' object")
        runtime = self.install.get("runtimeArtifact", DEFAULT_CFW_RUNTIME_ARTIFACT)
        if runtime is None:
            return None
        if not isinstance(runtime, dict):
            raise ModuleError("chocolatey install.runtimeArtifact must be an object")
        unknown = sorted(set(runtime) - _RUNTIME_FIELDS)
        if unknown:
            raise ModuleError(f"unknown Chocolatey runtimeArtifact field: {unknown[0]}")
        for field_name in ("id", "url", "evidenceUrl", "manifestUrl", "manifestSha256", "wineImage"):
            value = runtime.get(field_name)
            if not isinstance(value, str) or not value:
                raise ModuleError(f"chocolatey runtimeArtifact.{field_name} must be a non-empty string")
        if not _RUNTIME_ID_RE.fullmatch(runtime["id"]):
            raise ModuleError("chocolatey runtimeArtifact.id must be a safe cache identifier")
        for field_name in ("manifestSha256",):
            if not _SHA256_RE.fullmatch(runtime[field_name]):
                raise ModuleError(f"chocolatey runtimeArtifact.{field_name} must be a complete lowercase sha256")
        if not _WINE_IMAGE_RE.fullmatch(runtime["wineImage"]):
            raise ModuleError(
                "chocolatey runtimeArtifact.wineImage must be a digest-pinned "
                "ghcr.io/pelagians/cage-wine image"
            )
        for field_name in ("url", "evidenceUrl", "manifestUrl"):
            self._validate_runtime_source(field_name, runtime[field_name])
        wine_versions = runtime.get("wineVersions")
        if wine_versions != ["wine-11.0"]:
            raise ModuleError("Chocolatey Phase 1 supports exactly Wine 11 (wine-11.0)")
        environment = runtime.get("environment")
        if environment != {"WINEDLLOVERRIDES": ""}:
            raise ModuleError(
                "chocolatey runtimeArtifact.environment must be exactly "
                "{'WINEDLLOVERRIDES': ''} for Phase 1"
            )
        return {
            "id": runtime["id"],
            "url": runtime["url"],
            "evidenceUrl": runtime["evidenceUrl"],
            "manifestUrl": runtime["manifestUrl"],
            "manifestSha256": runtime["manifestSha256"],
            "wineImage": runtime["wineImage"],
            "wineVersions": ["wine-11.0"],
            "environment": {"WINEDLLOVERRIDES": ""},
        }

    def build(self) -> list[BuildStep]:
        self.validate()
        packages = self._packages()
        runtime = self._runtime_artifact()

        values = {
            "PACKAGE_ARGS": " ".join(shlex.quote(package) for package in packages),
            "SOURCE_ARG": (
                " -s '" + self.package_source.replace("'", "'\"'\"'") + "'" if self.package_source else ""
            ),
            "SMOKE_NUPKG_BASE64": base64.b64encode(
                load_asset_bytes("cage-chocolatey-smoke.0.1.0.nupkg")
            ).decode("ascii"),
            "SMOKE_NUPKG_SHA256": asset_sha256("cage-chocolatey-smoke.0.1.0.nupkg"),
            "POWERSHELL_HOST_FEATURE": "powershellHost",
            "POWERSHELL_HOST_POLICY": "disabled",
            "ALLOW_GLOBAL_CONFIRMATION_POLICY": "disabled",
        }
        asset_names = (
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "seed-cfw-runtime.sh",
            "runtime-artifact.py",
            "verify-chocolatey.sh",
            "feature-policy.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
            "cage-chocolatey-smoke.0.1.0.nupkg",
        )
        asset_hashes = {name: asset_sha256(name) for name in asset_names}

        runtime_id = runtime["id"] if runtime else DEFAULT_CFW_RUNTIME_PROFILE_ID
        common_metadata: dict[str, Any] = {
            "runtimeId": runtime_id,
            "runtimeProvider": CFW_RUNTIME_PROVIDER,
            "runtimeAvailable": runtime is not None,
        }
        steps: list[BuildStep] = [BuildStep(
            commands=[_record_command(runtime, asset_hashes)],
            description="Record CFW prepared runtime profile",
            kind="metadata",
            metadata={**common_metadata, "output": "metadata/chocolatey-runtime-profile.json"},
        )]

        if runtime is None:
            seed_script = (
                "echo '[cage] ERROR: no released CFW prepared runtime is pinned' >&2\n"
                "echo '[cage] Supply install.runtimeArtifact or use a Cage release with a built-in CFW runtime profile' >&2\n"
                "exit 65"
            )
            steps.append(BuildStep(
                commands=[seed_script],
                description="Require released CFW prepared prefix",
                kind="prefix-seed",
                metadata={**common_metadata, "status": "unreleased"},
            ))
        else:
            profile_json = json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
            values.update({
                "CFW_RUNTIME_PROFILE_BASE64": base64.b64encode(profile_json).decode("ascii"),
                "CFW_RUNTIME_PROFILE_KEY": runtime["manifestSha256"],
                "CFW_RUNTIME_HELPER_BASE64": base64.b64encode(
                    load_asset_bytes("runtime-artifact.py")
                ).decode("ascii"),
            })
            common_metadata.update({
                "runtimeManifestSha256": runtime["manifestSha256"],
                "wineImage": runtime["wineImage"],
                "wineVersions": runtime["wineVersions"],
            })
            fetch_helper = load_asset("fetch-verified.sh").rstrip()
            steps.append(BuildStep(
                commands=[fetch_helper + "\n\n" + render_asset("seed-cfw-runtime.sh", values)],
                description="Seed CFW prepared prefix",
                kind="prefix-seed",
                timeout=1800,
                metadata={
                    **common_metadata,
                    "scriptAsset": "core/chocolatey/assets/seed-cfw-runtime.sh",
                    "scriptSha256": asset_hashes["seed-cfw-runtime.sh"],
                    "runtimeEvidence": "metadata/cfw-runtime.json",
                    "runtimeManifest": "metadata/cfw-runtime-manifest.json",
                },
            ))

        failure_helper = load_asset("failure-diagnostics.sh").rstrip()
        for asset_name, description, kind, timeout in _POST_SEED_STEP_SPECS:
            if asset_name == "install-package.sh" and not packages:
                continue
            script = render_asset(asset_name, values)
            if asset_name in _FAILURE_DIAGNOSTIC_ASSETS:
                script = failure_helper + "\n\n" + script
            metadata: dict[str, Any] = {
                **common_metadata,
                "scriptAsset": f"core/chocolatey/assets/{asset_name}",
                "scriptSha256": asset_hashes[asset_name],
            }
            if asset_name == "verify-chocolatey.sh":
                metadata["diagnostic"] = "metadata/chocolatey-diagnostic.json"
            elif asset_name == "feature-policy.sh":
                metadata["featurePolicyEvidence"] = "metadata/chocolatey-feature-policy.json"
            elif asset_name == "smoke-lifecycle.sh":
                metadata["smokeEvidence"] = "metadata/chocolatey-smoke.json"
            steps.append(BuildStep(
                commands=[script],
                description=(
                    f"Install Chocolatey packages: {' '.join(packages)}"
                    if asset_name == "install-package.sh" else description
                ),
                kind=kind,
                timeout=timeout,
                metadata=metadata,
            ))
        return steps

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.install is not None:
            install = dict(self.install)
            runtime = self._runtime_artifact()
            if runtime is not None:
                install["runtimeArtifact"] = runtime
            result["install"] = install
        if self.package_source is not None:
            result["packageSource"] = self.package_source
        return result


__all__ = [
    "ChocolateyModule",
    "DEFAULT_CFW_RUNTIME_PROFILE_ID",
    "DEFAULT_CFW_RUNTIME_ARTIFACT",
    "CFW_RUNTIME_PROVIDER",
]
