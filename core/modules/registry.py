"""Registry imports and structured changes through Wine regedit."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import re
import shlex

from core.build_step import BuildStep
from core.sources import container_source_path
from .base import ModuleBase, ModuleError

_ROOTS = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE"}
_TYPES = {"string", "expandString", "dword", "qword", "binary"}


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def compile_reg(changes: list[dict[str, object]]) -> str:
    lines = ["Windows Registry Editor Version 5.00", ""]
    for change in changes:
        key = str(change["key"])
        root, separator, tail = key.partition("\\")
        if not separator or root not in _ROOTS or not tail or any(part in {"", ".", ".."} for part in tail.split("\\")) or re.search(r"[\x00-\x1f\x7f\[\]]", key):
            raise ModuleError(f"registry key must start with HKCU or HKLM and contain a safe subkey: {key}")
        action = change["action"]
        if action == "deleteKey":
            lines.extend([f"[-{_ROOTS[root]}\\{tail}]", ""])
            continue
        lines.append(f"[{_ROOTS[root]}\\{tail}]")
        name = change.get("name")
        name_field = "@" if name is None else '"' + _escape(str(name)) + '"'
        if action == "deleteValue":
            lines.append(f"{name_field}=-")
        else:
            kind, value = change.get("type", "string"), change.get("value")
            if kind == "string":
                if not isinstance(value, str):
                    raise ModuleError("registry string value must be a string")
                encoded = '"' + _escape(str(value)) + '"'
            elif kind in {"dword", "qword"}:
                if type(value) is not int or value < 0 or value >= 2 ** (32 if kind == "dword" else 64):
                    raise ModuleError(f"registry {kind} value is out of range")
                encoded = f"dword:{value:08x}" if kind == "dword" else "hex(b):" + ",".join(f"{byte:02x}" for byte in value.to_bytes(8, "little"))
            elif kind == "binary":
                if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2})*", value):
                    raise ModuleError("registry binary value must be an even-length hex string")
                encoded = "hex:" + ",".join(value[i:i+2].lower() for i in range(0, len(value), 2))
            elif kind == "expandString":
                if not isinstance(value, str):
                    raise ModuleError("registry expandString value must be a string")
                encoded = "hex(2):" + ",".join(f"{byte:02x}" for byte in (value + "\0").encode("utf-16le"))
            else:
                raise ModuleError(f"unsupported registry value type: {kind}")
            lines.append(f"{name_field}={encoded}")
        lines.append("")
    return "\n".join(lines) + "\n"


@dataclass
class RegistryModule(ModuleBase):
    type: str = "registry"
    file: str | None = None
    changes: list[dict[str, object]] | None = None
    sha256: str | None = None
    view: str = "default"
    user: str = "application"

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"type": self.type}
        for name, value in (("file", self.file), ("changes", self.changes), ("sha256", self.sha256)):
            if value is not None:
                payload[name] = value
        if self.view != "default": payload["view"] = self.view
        if self.user != "application": payload["user"] = self.user
        return payload

    def build(self) -> list[BuildStep]:
        if self.file:
            source = shlex.quote(container_source_path(self.file))
            commands = [f"wine regedit /S {source}"]
            if self.sha256:
                commands.insert(0, f"echo {shlex.quote(self.sha256.lower() + '  ' + container_source_path(self.file))} | sha256sum -c -")
        else:
            encoded = base64.b64encode(compile_reg(self.changes or []).encode("utf-16")).decode("ascii")
            commands = [f"printf %s {shlex.quote(encoded)} | base64 -d > /tmp/cage-registry-$$.reg",
                        'wine regedit /S /tmp/cage-registry-$$.reg', 'rm -f /tmp/cage-registry-$$.reg']
        return [BuildStep(commands, "Apply Wine registry changes", kind="registry",
                          metadata={"prefix": "active", "view": self.view, "user": self.user,
                                    "sha256": self.sha256,
                                    "source": self.file, "changes": self.changes})]
