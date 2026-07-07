"""Winetricks module expander."""
from __future__ import annotations

from typing import Any

from .base import WinetricksModule, ModuleError


def expand_winetricks(module: WinetricksModule, index: int) -> dict[str, Any]:
    """Expand winetricks module into dependencies."""
    # Merge defaults with user-provided fields
    verbs = module.verbs
    
    if module.defaults:
        default_verbs = module.defaults.get("verbs", [])
        if verbs is None:
            verbs = default_verbs
        elif default_verbs:
            # Combine user verbs with default verbs (user first, then defaults)
            verbs = list(verbs) + [v for v in default_verbs if v not in verbs]
    
    if not verbs:
        raise ModuleError(f"modules[{index}].verbs is required for winetricks module")
    
    if not isinstance(verbs, list) or not verbs:
        raise ModuleError(f"modules[{index}].verbs must be a non-empty list")
    
    return {
        "dependencies": [
            {"kind": "winetricks", "verbs": verbs}
        ]
    }
