"""Script recipe module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

@dataclass
class ScriptModule(ModuleBase):
    """Script execution module."""
    type: str = "script"
    command: str | None = None
    working_directory: str | None = None

    def build(self) -> list[BuildStep]:
        """Generate build steps for script execution."""
        if not self.command:
            raise ModuleError("script module requires 'command' field")

        commands = [
            f'echo "  Running script: {self.command[:50]}..."',
            self.command,
        ]

        return [BuildStep(
            commands=commands,
            description=f"Run script: {self.command[:50]}...",
            working_dir=self.working_directory,
            kind="raw-shell",
            unsafe=True,
            metadata={"escapeHatch": "script"},
        )]
