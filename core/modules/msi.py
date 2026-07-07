"""MSI installer module expander."""
from __future__ import annotations

from typing import Any

from .base import MsiModule, ModuleError


def expand_msi(module: MsiModule, index: int) -> dict[str, Any]:
    """Expand msi module into install step."""
    # Merge defaults with user-provided fields
    source = module.source
    sha256 = module.sha256
    silentArgs = module.silentArgs
    
    if module.defaults:
        source = source or module.defaults.get("source")
        sha256 = sha256 or module.defaults.get("sha256")
        silentArgs = silentArgs if silentArgs is not None else module.defaults.get("silentArgs")
    
    if not source:
        raise ModuleError(f"modules[{index}].source is required for msi module")
    
    install_step = {
        "kind": "msi",
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
