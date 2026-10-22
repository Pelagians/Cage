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
from core.chocolatey.assets.runtime_artifact import HOSTNAME_RE, UNSAFE_SOURCE_RE, validate_profile

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
_DEFAULT_CFW_RUNTIME_ASSET = "cfw-runtime-v1.0.7-wine-11.0.json"
DEFAULT_CFW_RUNTIME_ARTIFACT: dict[str, Any] = json.loads(load_asset(_DEFAULT_CFW_RUNTIME_ASSET))
DEFAULT_CFW_RUNTIME_PROFILE_ID = DEFAULT_CFW_RUNTIME_ARTIFACT["id"]
CFW_RUNTIME_PROVIDER = "cfw-chocolatey-runtime"
DEFAULT_CHOCOLATEY_PACKAGE_SOURCE = "https://community.chocolatey.org/api/v2/"

_READINESS_STEPS = (
    ("verify-chocolatey.sh", "Diagnose Chocolatey readiness", 600, "diagnostic", "metadata/chocolatey-diagnostic.json"),
    ("feature-policy.sh", "Verify Chocolatey external-host policy", 360, "featurePolicyEvidence", "metadata/chocolatey-feature-policy.json"),
    ("smoke-lifecycle.sh", "Prove Chocolatey local package lifecycle", 1800, "smokeEvidence", "metadata/chocolatey-smoke.json"),
)


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
    packages: list[str] | None = None
    package_source: str | None = None

    def validate(self) -> None:
        self._packages()
        self._runtime_artifact()
        source = self.package_source or DEFAULT_CHOCOLATEY_PACKAGE_SOURCE
        if UNSAFE_SOURCE_RE.search(source):
            raise ModuleError("chocolatey packageSource contains unsafe characters")
        parsed = urlparse(source)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or HOSTNAME_RE.fullmatch(parsed.hostname) is None
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
        packages = self.packages if self.packages is not None else (self.install or {}).get("packages")
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
        normalized_packages = [package.casefold() for package in packages]
        if len(normalized_packages) != len(set(normalized_packages)):
            raise ModuleError("chocolatey module 'install.packages' must not contain duplicates")
        return packages

    def _runtime_artifact(self) -> dict[str, Any] | None:
        runtime = (self.install or {}).get("runtimeArtifact", DEFAULT_CFW_RUNTIME_ARTIFACT)
        if runtime is None:
            return None
        try:
            validate_profile(runtime)
        except ValueError as exc:
            raise ModuleError(str(exc)) from exc
        return {**{key: value for key, value in runtime.items() if value is not None},
                "wineVersions": list(runtime["wineVersions"]),
                "environment": dict(runtime["environment"])}

    def foundation_steps(self) -> list[BuildStep]:
        """Verify and seed the producer runtime once, before application modules."""
        self.validate()
        runtime = self._runtime_artifact()
        values = {
            "SMOKE_NUPKG_BASE64": base64.b64encode(
                load_asset_bytes("cage-chocolatey-smoke.0.1.0.nupkg")
            ).decode("ascii"),
            "SMOKE_NUPKG_SHA256": asset_sha256("cage-chocolatey-smoke.0.1.0.nupkg"),
        }
        asset_names = (
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "seed-cfw-runtime.sh",
            "runtime_artifact.py",
            "verify-chocolatey.sh",
            "feature-policy.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
            "package-evidence.py",
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
                    load_asset_bytes("runtime_artifact.py")
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
        for asset_name, description, timeout, evidence_key, evidence_path in _READINESS_STEPS:
            steps.append(BuildStep(
                commands=[failure_helper + "\n\n" + render_asset(asset_name, values)],
                description=description,
                kind="wine-run",
                timeout=timeout,
                metadata={**common_metadata, "scriptAsset": f"core/chocolatey/assets/{asset_name}",
                          "scriptSha256": asset_hashes[asset_name], evidence_key: evidence_path},
            ))
        return steps

    def build(self) -> list[BuildStep]:
        """Only install packages at this module's declared position."""
        self.validate()
        packages = self._packages()
        if not packages:
            return []
        runtime = self._runtime_artifact()
        source = self.package_source or DEFAULT_CHOCOLATEY_PACKAGE_SOURCE
        values = {
            "PACKAGE_ARGS": " ".join(shlex.quote(package) for package in packages),
            "PACKAGE_SOURCE": source,
            "SOURCE_ARG": " -s '" + source + "'",
            "REQUESTED_PACKAGES_JSON": json.dumps(packages, separators=(",", ":")),
            "PACKAGE_EVIDENCE_HELPER_BASE64": base64.b64encode(load_asset_bytes("package-evidence.py")).decode("ascii"),
        }
        return [BuildStep(
            commands=[render_asset("install-package.sh", values)],
            description=f"Install Chocolatey packages: {' '.join(packages)}",
            kind="wine-run",
            timeout=1800,
            metadata={
                "runtimeId": runtime["id"] if runtime else DEFAULT_CFW_RUNTIME_PROFILE_ID,
                "runtimeProvider": CFW_RUNTIME_PROVIDER,
                "runtimeAvailable": runtime is not None,
                "scriptAsset": "core/chocolatey/assets/install-package.sh",
                "scriptSha256": asset_sha256("install-package.sh"),
                "packageEvidence": "metadata/chocolatey-package-evidence.json",
                "requestedPackages": packages,
                **({"runtimeManifestSha256": runtime["manifestSha256"], "wineImage": runtime["wineImage"],
                    "wineVersions": runtime["wineVersions"]} if runtime else {}),
            },
        )]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.install is not None or self.packages is not None:
            install = dict(self.install or {})
            runtime = self._runtime_artifact()
            if runtime is not None:
                install["runtimeArtifact"] = runtime
            result["install"] = install
        if self.packages is not None:
            result["packages"] = self.packages
        if self.package_source is not None:
            result["packageSource"] = self.package_source
        return result


__all__ = [
    "ChocolateyModule",
    "DEFAULT_CFW_RUNTIME_PROFILE_ID",
    "DEFAULT_CFW_RUNTIME_ARTIFACT",
    "CFW_RUNTIME_PROVIDER",
]
