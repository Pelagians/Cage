"""Msi recipe module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

@dataclass
class MsiModule(ModuleBase):
    """MSI installer module."""
    type: str = "msi"
    source: str | None = None
    sha256: str | None = None
    silentArgs: str | list[str] | None = None

    def build(self) -> list[BuildStep]:
        """Generate build steps for MSI installation."""
        if not self.source:
            raise ModuleError("msi module requires 'source' field")

        # Build the silent args string
        args_str = "/qn"  # Default silent install
        if self.silentArgs:
            if isinstance(self.silentArgs, list):
                args_str = " ".join(["/qn"] + self.silentArgs)
            else:
                args_str = f"/qn {self.silentArgs}"

        commands = [
            f'echo "  Installing MSI: {self.source}"',
            f"msiexec /i {self.source} {args_str}".strip(),
        ]

        return [BuildStep(
            commands=commands,
            description=f"Install MSI: {self.source}",
            kind="wine-msiexec",
        )]
