"""Deterministic Chocolatey module composed behind Cage's Synchro layer."""
from __future__ import annotations

from dataclasses import dataclass
import base64
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
    load_asset_bytes,
    render_asset,
)

from .base import ModuleBase, ModuleError
from .powershell_engine import WINDOWS_POWERSHELL_PROVIDER, windows_powershell51_steps
from .powershell_wrapper import DEFAULT_WRAPPER_VERSION, windows_powershell_wrapper_steps
from ..build_step import BuildStep

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9._+\-]+$")
CFW_CONTRACT_COMMIT = "c3b4923d0f63188843bd2a15be64bca8f4a9902b"
_PROFILE_ASSETS = (
    "profile-20-chocolatey.ps1",
    "profile-30-cfw-winetricks.ps1",
    "profile-40-cfw-command-adapters.ps1",
)
_FAILURE_DIAGNOSTIC_ASSETS = {
    "verify-chocolatey.sh",
    "feature-policy.sh",
    "smoke-lifecycle.sh",
}
_POST_LAYER_STEP_SPECS = (
    ("install-profile-fragments.sh", "Install CFW compatibility profile fragments", "wine-run", 120),
    ("verify-powershell-layer.sh", "Prove composed PowerShell compatibility layer", "wine-run", 600),
    ("verify-chocolatey.sh", "Diagnose Chocolatey readiness", "wine-run", 600),
    ("feature-policy.sh", "Apply Chocolatey feature policy", "wine-run", 360),
    ("smoke-lifecycle.sh", "Prove Chocolatey local package lifecycle", "wine-run", 1800),
    ("install-package.sh", "Install Chocolatey packages", "wine-run", 1800),
)


def _profile_record_command(profile_payload: dict[str, Any], asset_hashes: dict[str, str]) -> str:
    payload = {
        "schemaVersion": "cage.chocolatey-bootstrap/v1",
        "profile": profile_payload,
        "assets": asset_hashes,
        "layers": {
            "engine": WINDOWS_POWERSHELL_PROVIDER,
            "windowsPowerShellShim": f"synchro-{DEFAULT_WRAPPER_VERSION}",
            "cfwContractCommit": CFW_CONTRACT_COMMIT,
        },
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
    """Install Chocolatey packages using explicit, independently owned layers."""

    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None
    bootstrap: str = DEFAULT_BOOTSTRAP_PROFILE_ID

    def capabilities(self) -> dict[str, str]:
        return {
            "engine": WINDOWS_POWERSHELL_PROVIDER,
            "winps-shim": f"synchro-{DEFAULT_WRAPPER_VERSION}",
            "package-manager": "chocolatey-2.6.0",
            "compatibility-pack": "chocolatey-for-wine-v1",
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
            "SMOKE_NUPKG_BASE64": base64.b64encode(
                load_asset_bytes("cage-chocolatey-smoke.0.1.0.nupkg")
            ).decode("ascii"),
            "SMOKE_NUPKG_SHA256": asset_sha256("cage-chocolatey-smoke.0.1.0.nupkg"),
            "CFW_CONTRACT_COMMIT": CFW_CONTRACT_COMMIT,
            "PROFILE_20_B64": base64.b64encode(load_asset_bytes(_PROFILE_ASSETS[0])).decode("ascii"),
            "PROFILE_30_B64": base64.b64encode(load_asset_bytes(_PROFILE_ASSETS[1])).decode("ascii"),
            "PROFILE_40_B64": base64.b64encode(load_asset_bytes(_PROFILE_ASSETS[2])).decode("ascii"),
        })
        asset_names = (
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "bootstrap.sh",
            "install-powershell51.sh",
            "install-profile-fragments.sh",
            "verify-powershell-layer.sh",
            "verify-chocolatey.sh",
            "feature-policy.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
            "cage-chocolatey-smoke.0.1.0.nupkg",
            *_PROFILE_ASSETS,
        )
        asset_hashes = {name: asset_sha256(name) for name in asset_names}
        common_metadata = {
            "bootstrapProfile": profile.id,
            "bootstrapRevision": profile.revision,
            "cfwContractCommit": CFW_CONTRACT_COMMIT,
            "powershellEngine": WINDOWS_POWERSHELL_PROVIDER,
            "synchroWrapper": DEFAULT_WRAPPER_VERSION,
        }
        steps: list[BuildStep] = [BuildStep(
            commands=[_profile_record_command(profile.to_dict(), asset_hashes)],
            description="Record layered Chocolatey bootstrap profile",
            kind="metadata",
            metadata={**common_metadata, "output": "metadata/chocolatey-bootstrap.json"},
        )]

        fetch_helper = load_asset("fetch-verified.sh").rstrip()
        bootstrap_script = fetch_helper + "\n\n" + render_asset("bootstrap.sh", values)
        steps.append(BuildStep(
            commands=[bootstrap_script],
            description="Bootstrap CFW prerequisites and Chocolatey",
            kind="wine-run",
            timeout=4200,
            metadata={
                **common_metadata,
                "scriptAsset": "core/chocolatey/assets/bootstrap.sh",
                "scriptSha256": asset_hashes["bootstrap.sh"],
                "transitionalBootstrap": True,
            },
        ))

        # CFW establishes .NET Framework and native expansion support. Cage then
        # builds the real Windows PowerShell 5.1 backend and installs Synchro as
        # the only public powershell.exe surface.
        steps.extend(windows_powershell51_steps())
        steps.extend(windows_powershell_wrapper_steps())

        failure_helper = load_asset("failure-diagnostics.sh").rstrip()
        for asset_name, description, kind, timeout in _POST_LAYER_STEP_SPECS:
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
            if asset_name == "verify-powershell-layer.sh":
                metadata["powerShellEvidence"] = "metadata/powershell-layer.json"
            if asset_name == "verify-chocolatey.sh":
                metadata["diagnostic"] = "metadata/chocolatey-diagnostic.json"
            if asset_name == "smoke-lifecycle.sh":
                metadata["smokeEvidence"] = "metadata/chocolatey-smoke.json"
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
