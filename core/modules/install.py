"""One application installer operation for EXE and MSI inputs."""
from __future__ import annotations

from dataclasses import dataclass
import re
import shlex

from core.build_step import BuildStep
from core.sources import container_source_path
from .base import ModuleBase, ModuleError


@dataclass
class InstallModule(ModuleBase):
    type: str = "install"
    source: str | None = None
    installer: str | None = None
    sha256: str | None = None
    args: list[str] | None = None
    working_directory: str | None = None
    environment: dict[str, str] | None = None
    timeout: int | None = None
    expected_exit_codes: list[int] | None = None

    def to_dict(self) -> dict[str, object]:
        values: dict[str, object] = {"type": self.type, "source": self.source or ""}
        for key, value in (("installer", self.installer), ("sha256", self.sha256),
                           ("args", self.args), ("workingDirectory", self.working_directory),
                           ("environment", self.environment), ("timeout", self.timeout),
                           ("expectedExitCodes", self.expected_exit_codes)):
            if value is not None:
                values[key] = value
        return values

    def mechanism(self) -> str:
        if self.installer:
            return self.installer
        if not self.source:
            raise ModuleError("install.source is required")
        extension = self.source.lower().rsplit(".", 1)[-1]
        if extension not in {"exe", "msi"}:
            raise ModuleError("install.installer is required unless source ends in .exe or .msi")
        return extension

    def build(self) -> list[BuildStep]:
        if not self.source:
            raise ModuleError("install.source is required")
        mechanism = self.mechanism()
        source = self.source.replace("\\", "/")
        media = bool(re.fullmatch(r"[D-Yd-y]:/.*", source))
        if media:
            argument = shlex.quote(source)
        elif re.fullmatch(r"[Cc]:/.*", source):
            argument = shlex.quote(source)
        else:
            argument = shlex.quote(container_source_path(source))
        args = self.args if self.args is not None else (["/qn", "/norestart"] if mechanism == "msi" else [])
        runner = "wine msiexec /i" if mechanism == "msi" else "wine"
        code_values = self.expected_exit_codes if self.expected_exit_codes is not None else [0]
        # Capture every exit status, including zero. A mismatch with expected
        # code zero must itself fail with a nonzero build status.
        command = f"{runner} {argument} {' '.join(shlex.quote(arg) for arg in args)}".strip()
        allowed = "|".join(str(code) for code in code_values)
        commands = [f'if {command}; then rc=0; else rc=$?; fi',
                    f'case "$rc" in {allowed}) ;; *) printf "[cage] unexpected installer exit: %s\\n" "$rc" >&2; '
                    'if [ "$rc" -eq 0 ]; then exit 65; else exit "$rc"; fi ;; esac']
        if self.sha256 and not media:
            if re.fullmatch(r"[Cc]:/.*", source):
                raise ModuleError("install.sha256 for a prefix path is unsupported; use a verified workspace input")
            commands.insert(0, f"echo {shlex.quote(self.sha256.lower() + '  ' + container_source_path(source))} | sha256sum -c -")
        return [BuildStep(commands=commands, description=f"Install {mechanism.upper()}: {self.source}",
                          kind=f"install-{mechanism}", environment=self.environment or {},
                          working_dir=self.working_directory, timeout=self.timeout,
                          metadata={"installer": mechanism, "source": self.source,
                                    "sha256": self.sha256,
                                    "expectedExitCodes": code_values, "media": media})]
