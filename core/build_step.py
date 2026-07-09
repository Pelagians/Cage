"""Build step abstraction for module-first architecture."""
from __future__ import annotations

from dataclasses import dataclass, field
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

        for key, value in self.environment.items():
            lines.append(f"export {key}={_shell_quote(value)}")

        if self.working_dir:
            lines.append(f"cd {_shell_quote(self.working_dir)}")

        lines.extend(self.commands)
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
