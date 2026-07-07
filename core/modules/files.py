"""Files module expander.

Handles file and directory copying/mapping from host to container.
Expands into filesystem mappings that are applied in Phase 3 of the build.
"""
from __future__ import annotations

from typing import Any

from .base import FilesModule, ModuleError


def expand_files(module: FilesModule, index: int) -> dict[str, Any]:
    """Expand files module into filesystem mappings.
    
    Args:
        module: FilesModule instance with mappings field
        index: Module index for error messages
    
    Returns:
        Dict with 'filesystem' key containing list of FilesystemMapping dicts
    
    Raises:
        ModuleError: If mappings are missing or invalid
    """
    mappings = module.mappings
    
    if not mappings:
        raise ModuleError(f"modules[{index}].mappings is required for files module")
    
    filesystem_entries = []
    
    for i, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            raise ModuleError(f"modules[{index}].mappings[{i}] must be an object")
        
        source = mapping.get("source")
        target = mapping.get("target")
        
        if not source:
            raise ModuleError(f"modules[{index}].mappings[{i}].source is required")
        
        if not target:
            raise ModuleError(f"modules[{index}].mappings[{i}].target is required")
        
        entry = {
            "source": source,
            "target": target,
        }
        
        # Optional mode (defaults to "copy" in manifest parsing)
        mode = mapping.get("mode")
        if mode:
            if mode not in ("copy", "merge"):
                raise ModuleError(
                    f"modules[{index}].mappings[{i}].mode must be 'copy' or 'merge', got '{mode}'"
                )
            entry["mode"] = mode
        
        # Optional sha256 for source integrity verification
        sha256 = mapping.get("sha256")
        if sha256:
            entry["sha256"] = sha256
        
        filesystem_entries.append(entry)
    
    return {"filesystem": filesystem_entries}
