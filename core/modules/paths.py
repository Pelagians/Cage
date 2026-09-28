"""Shared build path classification and protected Linux artifact destinations."""
from __future__ import annotations

from pathlib import PurePosixPath
import re
import shlex

from .base import ModuleError

_PROTECTED = ("/init", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt/cage",
              "/etc/s6-overlay", "/etc/services.d", "/etc/cont-init.d", "/run", "/proc",
              "/etc/passwd", "/etc/group", "/etc/shadow", "/etc/sudoers",
              "/etc/ld.so.preload", "/sys", "/dev", "/tmp", "/workspace", "/work", "/var/run")


def validate_linux_output(path: str) -> str:
    """Limit captured image state to explicit application-owned absolute paths."""
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise ModuleError("Linux artifact output must be an absolute application path")
    if "\\" in path or any(part in {"", ".", ".."} for part in path[1:].split("/")):
        raise ModuleError(f"unsafe Linux artifact output: {path}")
    if any(path == item or path.startswith(item + "/") for item in _PROTECTED):
        raise ModuleError(f"Linux artifact output overlaps a protected runtime/build path: {path}")
    return path


def windows_prefix_target(path: str) -> str:
    normalized = path.replace("\\", "/")
    if not re.fullmatch(r"[Cc]:/[^\x00]+", normalized):
        raise ModuleError(f"expected an absolute C: prefix path: {path}")
    parts = normalized[3:].split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ModuleError(f"unsafe Windows prefix path: {path}")
    return '"$WINEPREFIX"/drive_c/' + shlex.quote("/".join(parts))


def build_input_path(source: str) -> str:
    from core.sources import container_source_path
    if re.match(r"^[Cc]:/", source):
        return windows_prefix_target(source)
    if re.match(r"^[D-Yd-y]:/", source):
        return shlex.quote(source)
    return shlex.quote(container_source_path(source))
