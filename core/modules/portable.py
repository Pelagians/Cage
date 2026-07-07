"""Portable app module expander."""
from __future__ import annotations

from typing import Any

from .base import PortableModule, ModuleError


def expand_portable(module: PortableModule, index: int) -> dict[str, Any]:
    """Expand portable module into install step."""
    # Merge defaults with user-provided fields
    source = module.source
    target = module.target
    config = module.config
    
    if module.defaults:
        source = source or module.defaults.get("source")
        target = target or module.defaults.get("target")
        config = config or module.defaults.get("config")
    
    if not source:
        raise ModuleError(f"modules[{index}].source is required for portable module")
    
    if not target:
        raise ModuleError(f"modules[{index}].target is required for portable module")
    
    install_step = {
        "kind": "portable",
        "source": source,
        "target": target,
    }
    
    if config:
        install_step["config"] = config
    
    return {"install": [install_step]}
