"""Script module expander."""
from __future__ import annotations

from typing import Any

from .base import ScriptModule, ModuleError


def expand_script(module: ScriptModule, index: int) -> dict[str, Any]:
    """Expand script module into install step."""
    # Merge defaults with user-provided fields
    command = module.command
    
    if module.defaults:
        command = command or module.defaults.get("command")
    
    if not command:
        raise ModuleError(f"modules[{index}].command is required for script module")
    
    install_step = {
        "kind": "script",
        "command": command,
    }
    
    return {"install": [install_step]}
