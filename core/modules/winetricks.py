"""Winetricks module expander."""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec, ModuleError


def expand_winetricks(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand winetricks module into dependencies."""
    if not module.verbs:
        raise ModuleError(f"modules[{index}].verbs is required for winetricks module")
    
    if not isinstance(module.verbs, list) or not module.verbs:
        raise ModuleError(f"modules[{index}].verbs must be a non-empty list")
    
    return {
        "dependencies": [
            {"kind": "winetricks", "verbs": module.verbs}
        ]
    }
