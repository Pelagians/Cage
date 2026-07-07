"""Script module expander."""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec, ModuleError


def expand_script(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand script module into install step."""
    if not module.command:
        raise ModuleError(f"modules[{index}].command is required for script module")
    
    install_step = {
        "kind": "script",
        "command": module.command,
    }
    
    return {"install": [install_step]}
