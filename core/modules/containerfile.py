"""Containerfile module expander.

This module type allows complex/odd-fix recipes to use raw fields
(dependencies, install, filesystem, registry, compatibility, sources, exports)
nested inside the module, similar to BlueBuild's approach.

Module composition: The containerfile module can nest other modules via the
`modules` field, allowing reusable module definitions with defaults.
"""
from __future__ import annotations

from typing import Any

from .base import ContainerfileModule, parse_module


def expand_containerfile(module: ContainerfileModule, index: int) -> dict[str, Any]:
    """Expand containerfile module by merging raw fields into recipe.
    
    Returns dict with all raw fields merged into recipe.
    If nested modules are present, they are expanded recursively.
    """
    result = {}
    
    # Handle nested modules (module composition)
    if module.modules:
        for nested_index, nested_data in enumerate(module.modules):
            nested_module = parse_module(nested_data, nested_index)
            # Recursively expand the nested module
            # We need to import apply_modules here to avoid circular imports
            from . import _expand_single_module
            nested_result = _expand_single_module(nested_module, nested_index)
            # Merge nested results into our result
            for key, value in nested_result.items():
                if key in result:
                    # Merge lists
                    if isinstance(result[key], list) and isinstance(value, list):
                        result[key].extend(value)
                    elif isinstance(result[key], dict) and isinstance(value, dict):
                        result[key].update(value)
                    else:
                        result[key] = value
                else:
                    result[key] = value
    
    # Merge raw fields (these take precedence over nested modules)
    if module.dependencies:
        result["dependencies"] = module.dependencies
    
    if module.install:
        # install field in containerfile is a list of raw install steps
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
