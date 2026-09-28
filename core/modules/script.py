"""Script recipe module."""
from __future__ import annotations

from dataclasses import dataclass
import shlex
from core.sources import container_source_path

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

@dataclass
class ScriptModule(ModuleBase):
    """Script execution module."""
    type: str = "script"
    working_directory: str | None = None
    run: str | None = None
    file: str | None = None
    sha256: str | None = None
    shell: str = "/bin/bash"
    environment: dict[str, str] | None = None
    timeout: int | None = None
    user: str = "root"
    outputs: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"type": "script"}
        for key, value in (("run", self.run), ("file", self.file), ("sha256", self.sha256),
                           ("shell", self.shell if self.shell != "/bin/bash" else None),
                           ("workingDirectory", self.working_directory),
                           ("environment", self.environment), ("timeout", self.timeout),
                           ("user", self.user if self.user != "root" else None), ("outputs", self.outputs)):
            if value is not None:
                result[key] = value
        return result

    def build(self) -> list[BuildStep]:
        """Generate build steps for script execution."""
        if self.file:
            source = container_source_path(self.file)
            commands = [f"{shlex.quote(self.shell)} {shlex.quote(source)}"]
            if self.sha256:
                commands.insert(0, f"echo {shlex.quote(self.sha256.lower() + '  ' + source)} | sha256sum -c -")
        else:
            commands = [f"{shlex.quote(self.shell)} -c {shlex.quote(self.run or '')}"]

        return [BuildStep(
            commands=commands,
            description=f"Run Linux script: {self.file or (self.run or '')[:50]}",
            working_dir=self.working_directory,
            kind="raw-shell",
            unsafe=True,
            environment=self.environment or {},
            timeout=self.timeout,
            metadata={"escapeHatch": "script", "executionUser": self.user, "outputs": self.outputs or [],
                      "source": self.file, "sha256": self.sha256},
        )]
