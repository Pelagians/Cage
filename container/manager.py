"""WinForge Container Manager.

Manages the lifecycle of WinForge Wine/Proton runtime OCI containers:
building, pulling, listing, and providing container metadata to the
builder pipeline.
"""
from __future__ import annotations
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_DIR = ROOT / "container" / "providers"

# Provider names must match runtime/providers.py names.
# directory_name may differ (e.g. provider "staging" → dir "wine-staging").
_CONTAINER_DEFS: dict[str, dict[str, Any]] = {
    "wine": {
        "directory_name": "wine",
        "image_prefix": "winforge/wine",
        "build_arg": "WINE_VERSION",
    },
    "staging": {
        "directory_name": "wine-staging",
        "image_prefix": "winforge/wine-staging",
        "build_arg": "WINE_VERSION",
    },
    "proton": {
        "directory_name": "proton",
        "image_prefix": "winforge/proton",
        "build_arg": "PROTON_VERSION",
    },
    "proton-ge": {
        "directory_name": "proton-ge",
        "image_prefix": "winforge/proton-ge",
        "build_arg": "GE_PROTON_TAG",
    },
}


def _def(provider: str) -> dict[str, Any] | None:
    raw = _CONTAINER_DEFS.get(provider)
    if raw is None:
        return None
    # Resolve directory path from directory_name
    d = dict(raw)
    d["directory"] = PROVIDER_DIR / d["directory_name"]
    d["dockerfile"] = d["directory"] / "Dockerfile"
    return d


@dataclass
class ContainerBuildResult:
    provider: str
    tag: str
    image_ref: str
    dockerfile_path: str
    success: bool
    log: str = ""

    def to_dict(self):
        return {
            "provider": self.provider,
            "tag": self.tag,
            "imageRef": self.image_ref,
            "dockerfile": self.dockerfile_path,
            "success": self.success,
            "log": self.log,
        }


def list_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "imagePrefix": d["image_prefix"],
            "buildArg": d["build_arg"],
            "directory": str((PROVIDER_DIR / d["directory_name"]).resolve()),
            "dockerfile": str((PROVIDER_DIR / d["directory_name"] / "Dockerfile").resolve()),
        }
        for name, d in _CONTAINER_DEFS.items()
    ]


def build_container(
    provider: str,
    version: str,
    *,
    registry: str | None = None,
    push: bool = False,
    build_cmd: str = "docker",
) -> ContainerBuildResult:
    definition = _def(provider)
    if not definition:
        msg = (f"Unknown provider: {provider}. "
               f"Known: {', '.join(_CONTAINER_DEFS)}")
        return ContainerBuildResult(provider, version, "", "", False, msg)

    dockerfile = definition["dockerfile"]
    if not dockerfile.exists():
        return ContainerBuildResult(
            provider, version, "", str(dockerfile), False,
            f"Dockerfile not found: {dockerfile}",
        )

    image_tag = f"{definition['image_prefix']}:{version}"
    registry_tag = f"{registry}/{image_tag}" if registry else ""

    cmd = [
        build_cmd, "build",
        "--build-arg", f"{definition['build_arg']}={version}",
        "-t", image_tag,
        "-f", str(dockerfile),
        str(ROOT),
    ]
    if registry_tag:
        cmd.extend(["-t", registry_tag])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
        log = result.stdout + result.stderr
        if result.returncode != 0:
            return ContainerBuildResult(
                provider, version, image_tag, str(dockerfile), False,
                f"Build failed (exit {result.returncode}):\n{log[-2000:]}",
            )

        if push and registry_tag:
            push_result = subprocess.run(
                [build_cmd, "push", registry_tag],
                capture_output=True, text=True, timeout=300,
            )
            if push_result.returncode != 0:
                log += (f"\nPush failed (exit {push_result.returncode}):\n"
                        f"{push_result.stderr[-1000:]}")

        return ContainerBuildResult(
            provider, version, image_tag, str(dockerfile), True, log,
        )

    except subprocess.TimeoutExpired:
        return ContainerBuildResult(
            provider, version, image_tag, str(dockerfile), False,
            "Build timed out after 600s",
        )
    except FileNotFoundError:
        return ContainerBuildResult(
            provider, version, image_tag, str(dockerfile), False,
            f"Command '{build_cmd}' not found. Install Docker or Podman.",
        )


def get_image_available(provider: str, version: str, *,
                        build_cmd: str = "docker") -> bool:
    definition = _def(provider)
    if not definition:
        return False
    image_ref = f"{definition['image_prefix']}:{version}"
    try:
        result = subprocess.run(
            [build_cmd, "image", "inspect", image_ref],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_image_ref(provider: str, version: str) -> str:
    definition = _def(provider)
    if definition:
        return f"{definition['image_prefix']}:{version}"
    return f"winforge/{provider}:{version}"
