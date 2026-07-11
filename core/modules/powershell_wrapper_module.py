"""Public recipe surface for the standalone PowerShell wrapper module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from .powershell_wrapper import DEFAULT_WRAPPER_VERSION
from ..build_step import BuildStep


@dataclass
class PowerShellWrapperModule(ModuleBase):
    """Reserved standalone Synchro module.

    The currently verified backend is Windows PowerShell 5.1 assembled after
    CFW's .NET Framework prerequisites. Until those prerequisites are factored
    into a standalone provider, recipes must request the Chocolatey module,
    which installs the backend and Synchro layer as one deterministic graph.
    """

    type: str = "powershell-wrapper"
    version: str = "7"
    wrapper_version: str = DEFAULT_WRAPPER_VERSION

    def capabilities(self) -> dict[str, str]:
        # Do not claim a provider for a module that cannot yet construct one.
        return {}

    def build(self) -> list[BuildStep]:
        raise ModuleError(
            "standalone powershell-wrapper is not supported on current Cage "
            "Wine runners; use the chocolatey module, which installs the "
            "verified Windows PowerShell 5.1 backend and Synchro v4.2.0 layer"
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.version != "7":
            result["version"] = self.version
        if self.wrapper_version != DEFAULT_WRAPPER_VERSION:
            result["wrapperVersion"] = self.wrapper_version
        return result


__all__ = ["PowerShellWrapperModule"]
