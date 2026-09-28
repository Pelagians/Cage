"""Winetricks recipe module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

@dataclass
class WinetricksModule(ModuleBase):
    """Winetricks verbs module."""
    type: str = "winetricks"
    verbs: list[str] | None = None

    def build(self) -> list[BuildStep]:
        """Generate build steps for winetricks verbs."""
        if not self.verbs:
            raise ModuleError("winetricks module requires 'verbs' field")

        verbs_str = " ".join(self.verbs)
        commands = [
            f'echo "  Installing winetricks verbs: {verbs_str}"',
            f"winetricks -q {verbs_str}",
        ]

        return [BuildStep(
            commands=commands,
            description=f"Install winetricks: {verbs_str}",
            kind="wine-run",
        )]
