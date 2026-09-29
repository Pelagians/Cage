"""Winetricks recipe module."""
from __future__ import annotations

from dataclasses import dataclass
import shlex
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
            f"printf '  Installing winetricks verbs: %s\\n' {shlex.quote(verbs_str)}",
            "winetricks -q " + " ".join(shlex.quote(verb) for verb in self.verbs),
        ]

        return [BuildStep(
            commands=commands,
            description=f"Install winetricks: {verbs_str}",
            kind="wine-run",
        )]
