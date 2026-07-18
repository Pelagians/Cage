"""Experimental standalone PowerShell wrapper module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from .powershell_engine import (
    POWERSHELL_VERSION,
    powershell_engine_steps,
)
from ..powershell_wrapper_assets import (
    POWERSHELL_WRAPPER_BASE_URL,
    POWERSHELL_WRAPPER_SHA256,
    POWERSHELL_WRAPPER_VERSION,
)
from ..build_step import BuildStep

DEFAULT_WRAPPER_VERSION = POWERSHELL_WRAPPER_VERSION
DEFAULT_WRAPPER_SHA256 = POWERSHELL_WRAPPER_SHA256

def _validate_version(wrapper_version: str) -> None:
    if wrapper_version != DEFAULT_WRAPPER_VERSION:
        raise ModuleError(
            "powershell-wrapper currently accepts only the pinned, checksummed "
            f"release {DEFAULT_WRAPPER_VERSION}; requested {wrapper_version}"
        )


def powershell_wrapper_steps(
    *,
    wine_prefix: str = "${WINEPREFIX:-$HOME/.wine}",
    version_slot: str = "7",
    wrapper_version: str = DEFAULT_WRAPPER_VERSION,
    include_engine: bool = True,
) -> list[BuildStep]:
    """Legacy PowerShell Core experiment retained for standalone diagnosis."""
    _validate_version(wrapper_version)
    steps: list[BuildStep] = []
    if include_engine:
        steps.extend(powershell_engine_steps(wine_prefix=wine_prefix, version_slot=version_slot))
    # The prepared CFW runtime owns Synchro and Windows compatibility. This
    # standalone experiment probes only the independent PowerShell Core engine.
    return steps


@dataclass
class PowerShellWrapperModule(ModuleBase):
    """Experimental standalone PowerShell Core module."""

    type: str = "powershell-wrapper"
    version: str = "7"
    wrapper_version: str = DEFAULT_WRAPPER_VERSION

    def capabilities(self) -> dict[str, str]:
        return {
            "engine": f"powershell-zip-{POWERSHELL_VERSION}",
            "winps-shim": f"synchro-{DEFAULT_WRAPPER_VERSION}-experimental",
        }

    def build(self) -> list[BuildStep]:
        return powershell_wrapper_steps(
            version_slot=self.version,
            wrapper_version=self.wrapper_version,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.version != "7":
            result["version"] = self.version
        if self.wrapper_version != DEFAULT_WRAPPER_VERSION:
            result["wrapperVersion"] = self.wrapper_version
        return result


__all__ = [
    "PowerShellWrapperModule",
    "DEFAULT_WRAPPER_VERSION",
    "DEFAULT_WRAPPER_SHA256",
    "powershell_wrapper_steps",
]
