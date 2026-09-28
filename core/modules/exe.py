"""Exe recipe module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

@dataclass
class ExeModule(ModuleBase):
    """EXE installer module."""
    type: str = "exe"
    source: str | None = None
    sha256: str | None = None
    silentArgs: str | list[str] | None = None

    def build(self) -> list[BuildStep]:
        """Generate build steps for EXE installation."""
        if not self.source:
            raise ModuleError("exe module requires 'source' field")

        # Build the silent args string
        args_str = ""
        if self.silentArgs:
            if isinstance(self.silentArgs, list):
                args_str = " ".join(self.silentArgs)
            else:
                args_str = self.silentArgs

        commands = [
            f'echo "  Installing {self.source}"',
            f"wine {self.source} {args_str}".strip(),
        ]

        return [BuildStep(
            commands=commands,
            description=f"Install EXE: {self.source}",
            kind="wine-run",
        )]
