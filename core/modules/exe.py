"""EXE installer module expander."""
from __future__ import annotations

from typing import Any

from .base import ExeModule, ModuleError


def expand_exe(module: ExeModule, index: int) -> dict[str, Any]:
    """Expand exe module into install step."""
    # Merge defaults with user-provided fields
    source = module.source
    sha256 = module.sha256
    silentArgs = module.silentArgs
    
    if module.defaults:
        source = source or module.defaults.get("source")
        sha256 = sha256 or module.defaults.get("sha256")
        silentArgs = silentArgs if silentArgs is not None else module.defaults.get("silentArgs")
    
    if not source:
        raise ModuleError(f"modules[{index}].source is required for exe module")
    
    install_step = {
        "kind": "exe",
        "source": source,
    }
    
    if sha256:
        install_step["sha256"] = sha256
    
    if silentArgs:
        if isinstance(silentArgs, list):
            install_step["args"] = silentArgs
        else:
            install_step["args"] = [silentArgs]
    
    return {"install": [install_step]}
