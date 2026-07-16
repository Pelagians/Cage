"""Deterministic Chocolatey module backed by CFW's integrated runtime."""
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
from ..build_step import BuildStep

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9._+\-]+$")
CFW_CONTRACT_COMMIT = "afeb4df45c09995f83153226e44350f26429afd0"
CFW_CONTAINER_RUNTIME_URL = (
    "https://raw.githubusercontent.com/noahgiroux/Chocolatey-for-wine/"
    f"{CFW_CONTRACT_COMMIT}/compat/container-runtime.sh"
)
CFW_CONTAINER_RUNTIME_SHA256 = "5dc10b6d54bb221a5793842be0247da54e956d95d0eb56c2e1c164daf4b7fc11"
CFW_RUNTIME_PROVIDER = "cfw-integrated-chocolatey-runtime"

_FAILURE_DIAGNOSTIC_ASSETS = {
    "verify-chocolatey.sh",
    "smoke-lifecycle.sh",
}
_POST_RUNTIME_STEP_SPECS = (
    ("verify-chocolatey.sh", "Diagnose Chocolatey readiness", "wine-run", 600),
    ("smoke-lifecycle.sh", "Prove Chocolatey local package lifecycle", "wine-run", 1800),
    ("install-package.sh", "Install Chocolatey packages", "wine-run", 1800),
)


def _profile_record_command(profile_payload: dict[str, Any], asset_hashes: dict[str, str]) -> str:
    payload = {
        "schemaVersion": "cage.chocolatey-bootstrap/v2",
        "profile": profile_payload,
        "assets": asset_hashes,
        "runtime": {
            "provider": CFW_RUNTIME_PROVIDER,
            "cfwContractCommit": CFW_CONTRACT_COMMIT,
            "packageExecutionHost": "chocolatey-in-process-powershell",
            "interactiveWindowsPowerShell": "optional",
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
    """Install Chocolatey packages through one CFW-owned runtime capability."""

    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None
    bootstrap: str = DEFAULT_BOOTSTRAP_PROFILE_ID

    def capabilities(self) -> dict[str, str]:
        return {
            "package-manager": "chocolatey-2.6.0",
            "package-execution-host": "chocolatey-in-process-powershell",
            "compatibility-runtime": CFW_RUNTIME_PROVIDER,
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
            "CFW_CONTAINER_RUNTIME_URL": CFW_CONTAINER_RUNTIME_URL,
            "CFW_CONTAINER_RUNTIME_SHA256": CFW_CONTAINER_RUNTIME_SHA256,
        })
        asset_names = (
            "fetch-verified.sh",
            "failure-diagnostics.sh",
            "bootstrap.sh",
            "finalize-cfw-runtime.sh",
            "verify-chocolatey.sh",
            "smoke-lifecycle.sh",
            "install-package.sh",
            "cage-chocolatey-smoke.0.1.0.nupkg",
        )
        asset_hashes = {name: asset_sha256(name) for name in asset_names}
        common_metadata = {
            "bootstrapProfile": profile.id,
            "bootstrapRevision": profile.revision,
            "cfwContractCommit": CFW_CONTRACT_COMMIT,
            "runtimeProvider": CFW_RUNTIME_PROVIDER,
        }

        steps: list[BuildStep] = [BuildStep(
            commands=[_profile_record_command(profile.to_dict(), asset_hashes)],
            description="Record CFW integrated runtime profile",
            kind="metadata",
            metadata={**common_metadata, "output": "metadata/chocolatey-bootstrap.json"},
        )]

        fetch_helper = load_asset("fetch-verified.sh").rstrip()
        steps.append(BuildStep(
            commands=[fetch_helper + "\n\n" + render_asset("bootstrap.sh", values)],
            description="Bootstrap CFW prerequisites and canonical Chocolatey",
            kind="wine-run",
            timeout=4200,
            metadata={
                **common_metadata,
                "scriptAsset": "core/chocolatey/assets/bootstrap.sh",
                "scriptSha256": asset_hashes["bootstrap.sh"],
            },
        ))
        steps.append(BuildStep(
            commands=[fetch_helper + "\n\n" + render_asset("finalize-cfw-runtime.sh", values)],
            description="Finalize CFW integrated Chocolatey runtime",
            kind="wine-run",
            timeout=1200,
            metadata={
                **common_metadata,
                "scriptAsset": "core/chocolatey/assets/finalize-cfw-runtime.sh",
                "scriptSha256": asset_hashes["finalize-cfw-runtime.sh"],
                "runtimeEvidence": "cfw-runtime/container-runtime.json",
            },
        ))

        failure_helper = load_asset("failure-diagnostics.sh").rstrip()
        for asset_name, description, kind, timeout in _POST_RUNTIME_STEP_SPECS:
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
