"""Chocolatey module backed by a verified CFW prepared-prefix artifact."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import re
import shlex
from typing import Any

from core.chocolatey import asset_sha256, load_asset, load_asset_bytes, render_asset

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9._+\-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_CFW_RUNTIME_PROFILE_ID = "cfw-runtime-v1"
DEFAULT_CFW_RUNTIME_ARTIFACT: dict[str, Any] | None = None
CFW_RUNTIME_PROVIDER = "cfw-chocolatey-runtime"
CFW_RUNTIME_ENGINE = "powershell-7.5.5-cfw-runtime"
CFW_RUNTIME_SHIM = "synchro-v4.2.0"

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
_RUNTIME_FIELDS = {"id", "url", "sha256", "evidenceUrl", "evidenceSha256", "wineVersions"}


def _record_command(runtime: dict[str, Any] | None, asset_hashes: dict[str, str]) -> str:
    payload = {
        "schemaVersion": "cage.chocolatey-runtime/v1",
        "runtime": runtime,
        "runtimeAvailable": runtime is not None,
        "assets": asset_hashes,
        "packageExecutionHost": "external-windows-powershell",
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
    source: str | None = None
    bootstrap: str = DEFAULT_CFW_RUNTIME_PROFILE_ID

    def capabilities(self) -> dict[str, str]:
        return {
            "engine": CFW_RUNTIME_ENGINE,
            "winps-shim": CFW_RUNTIME_SHIM,
            "package-manager": "chocolatey-2.6.0",
            "package-execution-host": "external-windows-powershell",
            "prefix-foundation": CFW_RUNTIME_PROVIDER,
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
                    "chocolatey package names must use letters, numbers, dots, underscores, plus, or dashes only: "
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
        for field_name in ("id", "url", "sha256", "evidenceUrl", "evidenceSha256"):
            value = runtime.get(field_name)
            if not isinstance(value, str) or not value:
                raise ModuleError(f"chocolatey runtimeArtifact.{field_name} must be a non-empty string")
        for field_name in ("sha256", "evidenceSha256"):
            if not _SHA256_RE.fullmatch(runtime[field_name]):
                raise ModuleError(f"chocolatey runtimeArtifact.{field_name} must be a complete lowercase sha256")
        for field_name in ("url", "evidenceUrl"):
            value = runtime[field_name]
            if not (value.startswith("https://") or value.startswith("file://") or value.startswith("/")):
                raise ModuleError(
                    f"chocolatey runtimeArtifact.{field_name} must use https://, file://, or an absolute path"
                )
        wine_versions = runtime.get("wineVersions")
        if not isinstance(wine_versions, list) or not wine_versions or not all(
            isinstance(version, str) and version for version in wine_versions
        ):
            raise ModuleError("chocolatey runtimeArtifact.wineVersions must be a non-empty string list")
        return {
            "id": runtime["id"],
            "url": runtime["url"],
            "sha256": runtime["sha256"],
            "evidenceUrl": runtime["evidenceUrl"],
            "evidenceSha256": runtime["evidenceSha256"],
            "wineVersions": list(wine_versions),
        }

    def build(self) -> list[BuildStep]:
        packages = self._packages()
        runtime = self._runtime_artifact()
        if self.source and not self.source.startswith("https://"):
            raise ModuleError(f"Invalid chocolatey source URL: {self.source}")

        values = {
            "PACKAGE_ARGS": " ".join(shlex.quote(package) for package in packages),
            "SOURCE_ARG": (
                " -s '" + self.source.replace("'", "'\"'\"'") + "'" if self.source else ""
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
            values.update({
                "BOOTSTRAP_PROFILE_ID": runtime["id"],
                "CFW_RUNTIME_ID": runtime["id"],
                "CFW_RUNTIME_URL": runtime["url"],
                "CFW_RUNTIME_SHA256": runtime["sha256"],
                "CFW_RUNTIME_EVIDENCE_URL": runtime["evidenceUrl"],
                "CFW_RUNTIME_EVIDENCE_SHA256": runtime["evidenceSha256"],
                "CFW_RUNTIME_WINE_VERSIONS": ",".join(runtime["wineVersions"]),
            })
            common_metadata.update({
                "runtimeArchiveSha256": runtime["sha256"],
                "runtimeEvidenceSha256": runtime["evidenceSha256"],
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
            result["install"] = self.install
        if self.source is not None:
            result["source"] = self.source
        if self.bootstrap != DEFAULT_CFW_RUNTIME_PROFILE_ID:
            result["bootstrap"] = self.bootstrap
        return result


__all__ = [
    "ChocolateyModule",
    "DEFAULT_CFW_RUNTIME_PROFILE_ID",
    "DEFAULT_CFW_RUNTIME_ARTIFACT",
    "CFW_RUNTIME_PROVIDER",
    "CFW_RUNTIME_ENGINE",
    "CFW_RUNTIME_SHIM",
]
