"""Build step abstraction for module-first architecture."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BuildStep:
    """A single build operation that produces shell commands.
    
    Build steps are the universal unit of work in Cage. Each module
    produces one or more build steps that are executed in declaration
    order during the build process.
    
    Attributes:
        commands: Shell commands to execute
        description: Human-readable description for logging
        environment: Optional environment variables to set before commands
        working_dir: Optional working directory for commands
        timeout: Optional timeout in seconds (None = no timeout)
    """
    commands: list[str]
    description: str
    environment: dict[str, str] = field(default_factory=dict)
    working_dir: str | None = None
    timeout: int | None = None
    
    def to_shell_lines(self) -> list[str]:
        """Convert this build step to shell script lines."""
        lines = []
        
        # Description comment
        if self.description:
            lines.append(f"# {self.description}")
        
        # Environment variables
        for key, value in self.environment.items():
            lines.append(f"export {key}={_shell_quote(value)}")
        
        # Working directory
        if self.working_dir:
            lines.append(f"cd {_shell_quote(self.working_dir)}")
        
        # Commands
        lines.extend(self.commands)
        
        return lines


def _shell_quote(value: str) -> str:
    """Quote a value for shell."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


__all__ = ["BuildStep"]
