"""Read-only operator-mounted ISO resource and Wine CD-ROM drive mapping."""
from __future__ import annotations

from dataclasses import dataclass
import shlex

from core.build_step import BuildStep
from core.sources import container_source_path
from .base import ModuleBase, ModuleError


@dataclass
class IsoModule(ModuleBase):
    type: str = "iso"
    action: str = "mount"
    id: str | None = None
    source: str | None = None
    drive: str | None = None
    backend: str = "host"
    mount_path: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"type": "iso", "action": self.action, "id": self.id or ""}
        for key, value in (("source", self.source), ("drive", self.drive),
                           ("backend", self.backend if self.action == "mount" else None),
                           ("mountPath", self.mount_path), ("sha256", self.sha256)):
            if value is not None: result[key] = value
        return result

    def build(self) -> list[BuildStep]:
        if not self.id:
            raise ModuleError("iso.id is required")
        if self.action == "unmount":
            return [BuildStep([], f"Release ISO media: {self.id}", kind="media-unmount",
                              metadata={"resource": self.id})]
        if self.backend != "host" or not self.mount_path or not self.source or not self.drive:
            raise ModuleError("iso mount requires source, drive and host mountPath; no privileged fallback exists")
        source = shlex.quote(container_source_path(self.source))
        mounted = shlex.quote(container_source_path(self.mount_path))
        drive = self.drive.upper()
        commands = [f"test -f {source}", f"test -d {mounted}",
                    f'test ! -e "$WINEPREFIX/dosdevices/{drive.lower()}:"',
                    f'ln -s -- {mounted} "$WINEPREFIX/dosdevices/{drive.lower()}:"',
                    f"wine reg add 'HKLM\\Software\\Wine\\Drives' /v '{drive}:' /t REG_SZ /d cdrom /f"]
        if self.sha256:
            commands.insert(1, f"echo {shlex.quote(self.sha256.lower() + '  ' + container_source_path(self.source))} | sha256sum -c -")
        return [BuildStep(commands, f"Expose read-only ISO: {self.id} on {drive}:", kind="media-mount",
                          metadata={"resource": self.id, "drive": drive, "backend": "host-mounted-read-only",
                                    "source": self.source, "sha256": self.sha256,
                                    "mountPath": self.mount_path})]
