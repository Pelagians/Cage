"""MSI installer module expander."""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec, ModuleError


def expand_msi(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand msi module into install step."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for msi module")
    
    install_step = {
        "kind": "msi",
        "source": module.source,
    }
    
    if module.sha256:
        install_step["sha256"] = module.sha256
    
    if module.silentArgs:
        if isinstance(module.silentArgs, list):
            install_step["args"] = module.silentArgs
        else:
            install_step["args"] = [module.silentArgs]
    
    return {"install": [install_step]}
