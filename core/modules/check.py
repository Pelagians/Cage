"""Small in-order file and command assertions."""
from __future__ import annotations

from dataclasses import dataclass
import shlex

from core.build_step import BuildStep
from .base import ModuleBase
from .paths import build_input_path


@dataclass
class CheckModule(ModuleBase):
    type: str = "check"
    file: dict[str, object] | None = None
    command: dict[str, object] | None = None

    def build(self) -> list[BuildStep]:
        if self.file:
            path = build_input_path(str(self.file["path"]))
            commands = [f"test {'-e' if self.file.get('exists', True) else '! -e'} {path}"]
            if self.file.get("sha256"):
                commands.append(f"test \"$(sha256sum -- {path} | cut -d ' ' -f1)\" = {shlex.quote(str(self.file['sha256']).lower())}")
        else:
            spec = self.command or {}
            command = str(spec.get("run", ""))
            expected = int(spec.get("exitCode", 0))
            commands = [f"{command} && rc=0 || rc=$?", f"test \"$rc\" -eq {expected}"]
        return [BuildStep(commands, "Verify application state", kind="check",
                          unsafe=bool(self.command), metadata={"file": self.file, "command": self.command})]
