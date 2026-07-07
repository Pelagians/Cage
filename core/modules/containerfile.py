"""Containerfile module expander.

This module type allows complex/odd-fix recipes to use raw fields
(dependencies, install, filesystem, registry, compatibility, sources, exports)
nested inside the module, similar to BlueBuild's approach.
"""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec


def expand_containerfile(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand containerfile module by merging raw fields into recipe.
    
    Returns dict with all raw fields that will be merged into the recipe.
    """
    result = {}
    
    if module.dependencies:
        result["dependencies"] = module.dependencies
    
    if module.install:
        # install field in containerfile is a dict with raw install steps
        # Convert to list format expected by recipe
        if isinstance(module.install, dict):
            # If it's a dict, treat it as a single install step
            result["install"] = [module.install]
        else:
            result["install"] = module.install
    
    if module.filesystem:
        result["filesystem"] = module.filesystem
    
    if module.registry:
        result["registry"] = module.registry
    
    if module.compatibility:
        result["compatibility"] = module.compatibility
    
    if module.sources:
        result["sources"] = module.sources
    
    if module.exports:
        result["exports"] = module.exports
    
    return result
