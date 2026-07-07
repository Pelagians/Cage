"""Portable app module expander."""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec, ModuleError


def expand_portable(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand portable module into extraction step."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for portable module")
    
    if not module.target:
        raise ModuleError(f"modules[{index}].target is required for portable module")
    
    install_step = {
        "kind": "script",
        "command": (
            f'# Extract portable app\n'
            f'PORTABLE_SOURCE="{module.source}"\n'
            f'PORTABLE_TARGET="{module.target}"\n'
            f'mkdir -p "$PORTABLE_TARGET"\n'
            f'if echo "$PORTABLE_SOURCE" | grep -qi "\\.zip$"; then\n'
            f'  unzip -q "$PORTABLE_SOURCE" -d "$PORTABLE_TARGET"\n'
            f'elif echo "$PORTABLE_SOURCE" | grep -qi "\\.7z$"; then\n'
            f'  7z x -y "$PORTABLE_SOURCE" -o"$PORTABLE_TARGET"\n'
            f'elif echo "$PORTABLE_SOURCE" | grep -qi "\\.tar"; then\n'
            f'  tar xf "$PORTABLE_SOURCE" -C "$PORTABLE_TARGET"\n'
            f'else\n'
            f'  echo "Unknown portable archive format: $PORTABLE_SOURCE"\n'
            f'  exit 1\n'
            f'fi'
        ),
    }
    
    result = {"install": [install_step]}
    
    # Optional config overlay
    if module.config:
        result["filesystem"] = [
            {"source": module.config, "target": "config.xml"}
        ]
    
    return result
