"""Safe archive extraction at its declared recipe position."""
from __future__ import annotations

from dataclasses import dataclass
import shlex

from core.build_step import BuildStep
from core.sources import container_source_path
from .base import ModuleBase
from .paths import build_input_path


@dataclass
class ExtractModule(ModuleBase):
    type: str = "extract"
    source: str | None = None
    target: str | None = None
    sha256: str | None = None
    max_bytes: int = 2 * 1024**3
    backend: str | None = None

    def archive_format(self) -> str:
        lower = (self.source or "").lower()
        if lower.endswith(".zip"): return "zip"
        if lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")): return "tar"
        if lower.endswith(".iso"): return "iso"
        raise ValueError("extract.source must have a tested ZIP, TAR or ISO extension")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"type": "extract", "source": self.source or "", "target": self.target or ""}
        if self.sha256: result["sha256"] = self.sha256
        if self.max_bytes != 2 * 1024**3: result["maxBytes"] = self.max_bytes
        if self.backend: result["backend"] = self.backend
        return result

    def build(self) -> list[BuildStep]:
        source = build_input_path(self.source or "")
        kind = self.archive_format()
        backend = self.backend or ("python-zipfile" if kind == "zip" else "python-tarfile")
        commands = []
        if self.sha256:
            commands.append(f"echo {shlex.quote(self.sha256.lower() + '  ' + container_source_path(self.source or ''))} | sha256sum -c -")
        commands.append(f"python3 /opt/cage/build/media.py {source} {shlex.quote(self.target or '')} --max-bytes {self.max_bytes} --format {kind}"
                        + (f" --backend {backend}" if kind == "iso" else ""))
        return [BuildStep(commands, f"Extract {self.source} to {self.target}", kind="extract",
                          metadata={"source": self.source, "sha256": self.sha256, "target": self.target,
                                    "backend": backend, "format": kind, "maxBytes": self.max_bytes})]
