"""Copy and merge workspace files into a Wine prefix."""
from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from typing import Any

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep


@dataclass
class FilesModule(ModuleBase):
    type: str = "files"
    mappings: list[dict[str, Any]] | None = None

    def build(self) -> list[BuildStep]:
        if not self.mappings:
            raise ModuleError("files module requires 'mappings' field")
        from core.sources import container_source_path

        commands: list[str] = []
        for mapping in self.mappings:
            source = mapping.get("source")
            target = mapping.get("target")
            if not source or not target:
                raise ModuleError("files module mapping requires 'source' and 'target'")
            mode = mapping.get("mode", "copy")
            if mode not in {"copy", "merge"}:
                raise ModuleError(f"unsupported files mapping mode: {mode}")
            normalized = target.replace("\\", "/")
            if not re.match(r"^[Cc]:/", normalized):
                raise ModuleError("files target must be an absolute C:/ path")
            parts = normalized[3:].split("/")
            if not parts or any(part in {"", ".", ".."} for part in parts):
                raise ModuleError(f"files target contains an unsafe path: {target}")
            dest = '"$WINEPREFIX"/drive_c/' + shlex.quote('/'.join(parts))
            src = shlex.quote(container_source_path(source))
            commands.append(f"test -e {src}")
            if mapping.get("sha256"):
                expected = mapping["sha256"]
                if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                    raise ModuleError("files mapping sha256 must be 64 hexadecimal characters")
                commands.append(f"test -f {src} && test \"$(sha256sum -- {src} | cut -d ' ' -f1)\" = {shlex.quote(expected.lower())}")
            if mode == "copy":
                commands.extend([
                    f"mkdir -p -- $(dirname -- {dest})",
                    f"rm -rf -- {dest}",
                    f"cp -a -- {src} {dest}",
                ])
            else:
                commands.extend([
                    f"test -d {src}",
                    f"mkdir -p -- {dest}",
                    f"cp -a -- {src}/. {dest}/",
                ])
        return [BuildStep(commands=commands, description=f"Copy {len(self.mappings)} file(s)", kind="copy-tree")]
