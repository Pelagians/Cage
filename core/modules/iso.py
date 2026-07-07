"""ISO installer module expander."""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec, ModuleError


def expand_iso(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand iso module into mount + autorun script."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for iso module")
    
    # Build ISO mount and autorun script
    script_parts = [
        "# Mount ISO and run autorun",
        f'ISO_SOURCE="{module.source}"',
        'ISO_MOUNT="/tmp/cage-iso-$RANDOM"',
        'mkdir -p "$ISO_MOUNT"',
        'mount -o loop,ro "$ISO_SOURCE" "$ISO_MOUNT" 2>/dev/null || '
        'mount -o ro "$ISO_SOURCE" "$ISO_MOUNT" 2>/dev/null || '
        '(echo "Failed to mount ISO: $ISO_SOURCE" >&2; exit 1)',
    ]
    
    if module.autorun:
        script_parts.extend([
            '# Run autorun',
            'if [ -f "$ISO_MOUNT/AUTORUN.INF" ]; then',
            '  echo "Found AUTORUN.INF"',
            'fi',
            'if [ -f "$ISO_MOUNT/setup.exe" ]; then',
            '  wine "$ISO_MOUNT/setup.exe"',
            'elif [ -f "$ISO_MOUNT/SETUP.EXE" ]; then',
            '  wine "$ISO_MOUNT/SETUP.EXE"',
            'elif [ -f "$ISO_MOUNT/install.exe" ]; then',
            '  wine "$ISO_MOUNT/install.exe"',
            'elif [ -f "$ISO_MOUNT/INSTALL.EXE" ]; then',
            '  wine "$ISO_MOUNT/INSTALL.EXE"',
            'else',
            '  echo "No setup.exe or install.exe found in ISO"',
            'fi',
        ])
    
    script_parts.extend([
        '# Cleanup',
        'umount "$ISO_MOUNT" 2>/dev/null || true',
        'rmdir "$ISO_MOUNT" 2>/dev/null || true',
    ])
    
    install_step = {
        "kind": "script",
        "command": "\n".join(script_parts),
    }
    
    return {"install": [install_step]}
