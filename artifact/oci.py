"""OCI image mapping model for WinForge bundles.

WinForge bundles can be mapped to OCI image layers on top of a
WinForge Wine/Proton runtime base image.  The result is a self-contained
OCI image that includes both the Wine runtime and the configured prefix.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OCIImageMapping:
    bundle_root: str = "/opt/winforge/bundle"
    prefix_path: str = "/opt/winforge/bundle/prefix"
    manifest_path: str = "/opt/winforge/bundle/manifest.winforge.json"
    runtime_path: str = "/opt/winforge/bundle/runtime/runtime.json"
    entrypoint_path: str = "/opt/winforge/bundle/launch/entrypoint.json"

    def labels(self) -> dict[str, str]:
        return {
            "org.opencontainers.image.title": "WinForge execution bundle",
            "org.opencontainers.image.description": (
                "Self-contained Wine/Proton execution environment built by WinForge"
            ),
            "dev.winforge.artifact.kind": "execution-bundle",
            "dev.winforge.artifact.version": "v0",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundleRoot": self.bundle_root,
            "prefixPath": self.prefix_path,
            "manifestPath": self.manifest_path,
            "runtimePath": self.runtime_path,
            "entrypointPath": self.entrypoint_path,
        }

    @classmethod
    def default(cls) -> OCIImageMapping:
        return cls()


def build_oci_image(
    bundle_path: Path,
    base_image: str,
    *,
    output_tag: str | None = None,
    build_cmd: str = "docker",
) -> dict[str, Any]:
    mapping = OCIImageMapping.default()
    dockerfile_content = (
        f"FROM {base_image}\n"
        f"\n"
        f"LABEL dev.winforge.artifact.kind=execution-bundle\n"
        f"LABEL dev.winforge.artifact.version=v0\n"
        f"\n"
        f"COPY {bundle_path.name} {mapping.bundle_root}\n"
    )
    return {
        "baseImage": base_image,
        "bundlePath": str(bundle_path),
        "outputTag": output_tag,
        "suggestedDockerfile": dockerfile_content,
    }
