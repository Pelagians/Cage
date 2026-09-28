"""Iso recipe module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

@dataclass
class IsoModule(ModuleBase):
    """ISO mount and run module."""
    type: str = "iso"
    source: str | None = None
    autorun: bool | None = None

    def build(self) -> list[BuildStep]:
        """Generate build steps for ISO mounting and execution."""
        if not self.source:
            raise ModuleError("iso module requires 'source' field")

        commands = [
            f'echo "  Mounting ISO: {self.source}"',
            f"MOUNT_POINT=$(mktemp -d)",
            f"mount -o loop {self.source} $MOUNT_POINT",
        ]

        if self.autorun:
            commands.extend([
                'echo "  Running autorun"',
                "wine $MOUNT_POINT/setup.exe || wine $MOUNT_POINT/autorun.exe",
            ])

        commands.extend([
            "umount $MOUNT_POINT",
            "rmdir $MOUNT_POINT",
        ])

        return [BuildStep(
            commands=commands,
            description=f"Mount and run ISO: {self.source}",
            kind="raw-shell",
        )]
