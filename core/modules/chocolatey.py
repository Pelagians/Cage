"""Deterministic, profile-backed Chocolatey module for Wine."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shlex
from typing import Any

from core.chocolatey import (
    DEFAULT_BOOTSTRAP_PROFILE_ID,
    ChocolateyAssetError,
    ChocolateyProfileError,
    asset_sha256,
    get_bootstrap_profile,
    load_asset,
    render_asset,
)

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9._+\-]+$")
_DOWNLOAD_ASSETS = {"powershell-msi.sh", "prepare-data.sh", "install-dotnet481.sh"}
_STEP_SPECS = (
    ("powershell-msi.sh", "Install PowerShell 7 MSI for Chocolatey", "wine-msiexec", 1200),
    ("prepare-data.sh", "Prepare Chocolatey-for-wine data", "extract", None),
    ("install-dotnet481.sh", "Install upstream .NET 4.8.1 manifest payload for Chocolatey", "extract", 1800),
    ("prepare-registry.sh", "Prepare Wine registry for Chocolatey", "wine-reg", 120),
    ("promote-chocolatey.sh", "Promote Chocolatey natively", "raw-shell", None),
    ("verify-chocolatey.sh", "Diagnose Chocolatey readiness", "wine-run", 120),
    ("install-package.sh", "Install Chocolatey packages", "wine-run", 1800),
)


def _profile_record_command(profile_payload: dict[str, str], asset_hashes: dict[str, str]) -> str:
    payload = {
        "schemaVersion": "cage.chocolatey-bootstrap/v0",
        "profile": profile_payload,
        "assets": asset_hashes,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return (
        "mkdir -p \"${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata\" && "
        "python3 -c 'import json,sys; from pathlib import Path; "
        "p=Path(sys.argv[1]); p.write_text(json.dumps(json.loads(sys.argv[2]), indent=2, sort_keys=True) + \"\\n\", encoding=\"utf-8\")' "
        '"${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-bootstrap.json" '
        + shlex.quote(encoded)
    )


@dataclass
class ChocolateyModule(ModuleBase):
    """Install Chocolatey packages using one immutable compatibility profile."""

    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None
    bootstrap: str = DEFAULT_BOOTSTRAP_PROFILE_ID

    def capabilities(self) -> dict[str, str]:
        return {
            "engine": "chocolatey-powershell-msi",
            "winps-shim": "chocolatey-native",
            "shim-library": "chocolatey-for-wine",
        }

    def _packages(self) -> list[str]:
        if not isinstance(self.install, dict):
            raise ModuleError("chocolatey module requires 'install' object")
        packages = self.install.get("packages")
        if not isinstance(packages, list) or not packages:
            raise ModuleError("chocolatey module 'install.packages' cannot be empty")
        if not all(isinstance(package, str) and package for package in packages):
            raise ModuleError("chocolatey module 'install.packages' must be a list of non-empty strings")
        for package in packages:
            if not _PACKAGE_RE.fullmatch(package):
                raise ModuleError(
                    "chocolatey package names must use letters, numbers, dots, underscores, plus, or dashes only: "
                    f"{package}"
                )
        return packages

    def build(self) -> list[BuildStep]:
        packages = self._packages()
        if self.source and not self.source.startswith("https://"):
            raise ModuleError(f"Invalid chocolatey source URL: {self.source}")

        try:
            profile = get_bootstrap_profile(self.bootstrap)
        except (ChocolateyAssetError, ChocolateyProfileError) as exc:
            raise ModuleError(str(exc)) from exc
        values = profile.template_values()
        values.update({
            "PACKAGE_ARGS": " ".join(shlex.quote(package) for package in packages),
            "SOURCE_ARG": (
                " -s '" + self.source.replace("'", "'\"'\"'") + "'"
                if self.source else ""
            ),
        })
        asset_hashes = {
            name: asset_sha256(name)
            for name in ("fetch-verified.sh", *(spec[0] for spec in _STEP_SPECS))
        }
        common_metadata = {
            "bootstrapProfile": profile.id,
            "bootstrapRevision": profile.revision,
        }
        steps = [BuildStep(
            commands=[_profile_record_command(profile.to_dict(), asset_hashes)],
            description="Record Chocolatey bootstrap profile",
            kind="metadata",
            metadata={
                **common_metadata,
                "output": "metadata/chocolatey-bootstrap.json",
            },
        )]

        fetch_helper = load_asset("fetch-verified.sh").rstrip()
        for asset_name, description, kind, timeout in _STEP_SPECS:
            script = render_asset(asset_name, values)
            if asset_name in _DOWNLOAD_ASSETS:
                script = fetch_helper + "\n\n" + script
            metadata: dict[str, Any] = {
                **common_metadata,
                "scriptAsset": f"core/chocolatey/assets/{asset_name}",
                "scriptSha256": asset_hashes[asset_name],
            }
            if asset_name == "verify-chocolatey.sh":
                metadata["diagnostic"] = "metadata/chocolatey-diagnostic.json"
            steps.append(BuildStep(
                commands=[script],
                description=(
                    f"Install Chocolatey packages: {' '.join(packages)}"
                    if asset_name == "install-package.sh"
                    else description
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
        if self.bootstrap != DEFAULT_BOOTSTRAP_PROFILE_ID:
            result["bootstrap"] = self.bootstrap
        return result
