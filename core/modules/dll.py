"""Ordered verified DLL deployment and Wine loader policy."""
from __future__ import annotations

from dataclasses import dataclass
import shlex

from core.build_step import BuildStep
from core.sources import container_source_path
from core.compatibility import DLL_OVERRIDE_VALUES
from .base import ModuleBase


@dataclass
class DllModule(ModuleBase):
    type: str = "dll"
    install: dict[str, str] | None = None
    overrides: dict[str, str] | None = None
    evidence: dict[str, str] | None = None

    def build(self) -> list[BuildStep]:
        steps: list[BuildStep] = []
        if self.install:
            source = container_source_path(self.install["source"])
            target = self.install["target"]
            name = self.install["source"].replace("\\", "/").rsplit("/", 1)[-1]
            destination = '"$WINEPREFIX"/drive_c/windows/' + target + '/' + shlex.quote(name)
            steps.append(BuildStep([
                f"echo {shlex.quote(self.install['sha256'].lower() + '  ' + source)} | sha256sum -c -",
                f"install -D -m 0644 -- {shlex.quote(source)} {destination}",
            ], f"Deploy verified DLL to {target}", kind="dll-deploy",
                metadata={"source": self.install["source"], "sha256": self.install["sha256"],
                          "target": target, "evidence": self.evidence}))
        if self.overrides:
            commands = ["wine reg add 'HKCU\\Software\\Wine\\DllOverrides' "
                        + f"/v {shlex.quote(name.lower().removesuffix('.dll'))} /t REG_SZ /d {shlex.quote(DLL_OVERRIDE_VALUES[policy])} /f"
                        for name, policy in self.overrides.items()]
            steps.append(BuildStep(commands, "Configure Wine DLL override policy", kind="dll-overrides",
                                   metadata={"overrides": self.overrides, "evidence": self.evidence}))
        return steps
