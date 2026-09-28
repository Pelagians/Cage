"""Portable recipe module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

@dataclass
class PortableModule(ModuleBase):
    """Portable app staging module."""
    type: str = "portable"
    source: str | None = None
    target: str | None = None

    def build(self) -> list[BuildStep]:
        """Generate build steps for portable app extraction."""
        if not self.source:
            raise ModuleError("portable module requires 'source' field")
        if not self.target:
            raise ModuleError("portable module requires 'target' field")

        commands = [
            f'echo "  Extracting portable app to {self.target}"',
            f"mkdir -p {self.target}",
            f"unzip -o {self.source} -d {self.target}",
        ]

        return [BuildStep(
            commands=commands,
            description=f"Extract portable: {self.source} → {self.target}",
            kind="extract",
        )]
