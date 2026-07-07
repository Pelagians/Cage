"""EXE installer module expander."""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec, ModuleError


def expand_exe(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand exe module into install step + optional config overlay."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for exe module")
    
    # Build install step
    install_step = {
        "kind": "exe",
        "source": module.source,
    }
    
    if module.sha256:
        install_step["sha256"] = module.sha256
    
    if module.silentArgs:
        if isinstance(module.silentArgs, list):
            install_step["args"] = module.silentArgs
        else:
            install_step["args"] = [module.silentArgs]
    
    result = {"install": [install_step]}
    
    # Optional config overlay
    if module.config:
        result["filesystem"] = [
            {"source": module.config, "target": "config.xml"}
        ]
    
    return result
