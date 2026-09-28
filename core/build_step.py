"""Build step abstraction for module-first architecture."""
from __future__ import annotations

from dataclasses import dataclass, field
import shlex
import re
from typing import Any


@dataclass(frozen=True)
class BuildStep:
    """A single build operation that produces shell commands.

    Build steps are the universal unit of work in Cage. Each module produces one
    or more build steps that are executed in declaration order during the build
    process. `kind` and `unsafe` are persisted into build-plan/provenance so
    failures can be attributed without parsing one giant shell blob.
    """

    commands: list[str]
    description: str
    kind: str = "raw-shell"
    environment: dict[str, str] = field(default_factory=dict)
    working_dir: str | None = None
    timeout: int | None = None
    unsafe: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_shell_lines(self) -> list[str]:
        """Convert this build step to shell script lines."""
        lines = []

        if self.description:
            lines.append(f"# {self.description}")

        body = []
        for key, value in self.environment.items():
            body.append(f"export {key}={_shell_quote(value)}")

        if self.working_dir:
            normalized = self.working_dir.replace("\\", "/")
            if re.match(r"^[A-Za-z]:/", normalized):
                drive = normalized[0].lower()
                suffix = normalized[3:]
                if ".." in suffix.split("/"):
                    raise ValueError("working directory escapes its Wine drive")
                body.append(f'cd -- "$WINEPREFIX/dosdevices/{drive}:"/{shlex.quote(suffix)}')
            else:
                body.append(f"cd {_shell_quote(self.working_dir)}")

        body.extend(self.commands)
        if self.timeout is not None:
            if not isinstance(self.timeout, int) or isinstance(self.timeout, bool) or self.timeout <= 0:
                raise ValueError("BuildStep.timeout must be a positive integer")
            script = "set -euo pipefail\n" + "\n".join(body)
            lines.append(
                f"timeout --signal=TERM --kill-after=15s {self.timeout}s "
                f"bash -c {shlex.quote(script)}"
            )
        elif self.working_dir or self.environment:
            lines.extend(["(", *body, ")"])
        else:
            lines.extend(body)
        return lines

    def to_dict(self) -> dict[str, Any]:
        """Serialize the build step into the machine-readable build plan."""
        payload: dict[str, Any] = {
            "kind": self.kind,
            "description": self.description,
            "commands": self.commands,
            "unsafe": self.unsafe,
        }
        if self.environment:
            payload["environment"] = self.environment
        if self.working_dir:
            payload["workingDir"] = self.working_dir
        if self.timeout is not None:
            payload["timeout"] = self.timeout
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


def _shell_quote(value: str) -> str:
    """Quote a value for shell."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


__all__ = ["BuildStep"]
