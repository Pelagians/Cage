"""Module expansion registry and main entry point."""
from __future__ import annotations

from typing import Any

from .base import (
    ModuleSpec, ModuleBase, ModuleError, parse_module,
    ChocolateyModule, ExeModule, MsiModule, IsoModule,
    WinetricksModule, PortableModule, FilesModule, ScriptModule, PowerShellModule, ContainerfileModule,
)
from .chocolatey import expand_chocolatey
from .exe import expand_exe
from .msi import expand_msi
from .iso import expand_iso
from .winetricks import expand_winetricks
from .portable import expand_portable
from .files import expand_files
from .script import expand_script
from .powershell import expand_powershell
from .containerfile import expand_containerfile


def _expand_single_module(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand a single module into its component parts.
    
    Returns a dict with keys like 'dependencies', 'install', 'filesystem', etc.
    Each key maps to a list (or dict for compatibility) that should be merged
    into the recipe's top-level fields.
    """
    if isinstance(module, ChocolateyModule):
        return expand_chocolatey(module, index)
    elif isinstance(module, ExeModule):
        return expand_exe(module, index)
    elif isinstance(module, MsiModule):
        return expand_msi(module, index)
    elif isinstance(module, IsoModule):
        return expand_iso(module, index)
    elif isinstance(module, WinetricksModule):
        return expand_winetricks(module, index)
    elif isinstance(module, PortableModule):
        return expand_portable(module, index)
    elif isinstance(module, FilesModule):
        return expand_files(module, index)
    elif isinstance(module, ScriptModule):
        return expand_script(module, index)
    elif isinstance(module, PowerShellModule):
        return expand_powershell(module, index)
    elif isinstance(module, ContainerfileModule):
        return expand_containerfile(module, index)
    else:
        raise ModuleError(f"unknown module type: {type(module).__name__}")


def apply_modules(recipe: dict[str, Any]) -> dict[str, Any]:
    """Expand all modules in a recipe and merge results into top-level fields.
    
    This function:
    1. Parses each module definition into a typed ModuleSpec
    2. Auto-injects implicit dependencies (e.g., powershell for chocolatey)
    3. Expands each module into its component parts (dependencies, install steps, etc.)
    4. Merges all expanded parts into the recipe's top-level fields
    5. Tracks module expansions in provenance.moduleExpansions
    6. Returns the modified recipe (modules field is removed after expansion)
    
    The recipe is modified in-place and also returned for convenience.
    """
    modules_data = recipe.get("modules", [])
    if not modules_data:
        return recipe
    
    # Auto-inject implicit dependencies
    has_chocolatey = any(m.get("type") == "chocolatey" for m in modules_data if isinstance(m, dict))
    has_powershell = any(m.get("type") == "powershell" for m in modules_data if isinstance(m, dict))
    
    # If chocolatey is used but powershell is not explicitly declared, inject it
    if has_chocolatey and not has_powershell:
        modules_data = [{"type": "powershell"}] + list(modules_data)
    
    # Parse all modules
    modules = [parse_module(data, i) for i, data in enumerate(modules_data)]
    
    # Expand each module and collect results
    expanded_parts = []
    module_expansions = []
    for i, module in enumerate(modules):
        try:
            part = _expand_single_module(module, i)
            expanded_parts.append(part)
            # Track expansion for provenance
            expansion_info = {
                "index": i,
                "type": module.type,
                "expanded_fields": list(part.keys()),
            }
            # Track injected dependencies and install steps
            if "dependencies" in part:
                expansion_info["injectedDependencies"] = part["dependencies"]
            if "install" in part:
                expansion_info["injectedInstallSteps"] = len(part["install"])
            module_expansions.append(expansion_info)
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(f"modules[{i}] expansion failed: {exc}") from exc
    
    # Merge all expanded parts into the recipe
    for part in expanded_parts:
        for key, value in part.items():
            if key in recipe:
                # Merge lists
                if isinstance(recipe[key], list) and isinstance(value, list):
                    recipe[key].extend(value)
                # Merge dicts (e.g., compatibility)
                elif isinstance(recipe[key], dict) and isinstance(value, dict):
                    recipe[key].update(value)
                else:
                    # Overwrite (shouldn't happen in normal usage)
                    recipe[key] = value
            else:
                recipe[key] = value
    
    # Track module expansions in provenance
    if "provenance" not in recipe:
        recipe["provenance"] = {}
    if not isinstance(recipe["provenance"], dict):
        recipe["provenance"] = {}
    recipe["provenance"]["moduleExpansions"] = module_expansions
    # Store the expanded modules list (including auto-injected) for re-parsing
    recipe["provenance"]["expandedModules"] = modules_data
    
    # Remove the modules field after expansion
    recipe.pop("modules", None)
    
    return recipe


__all__ = [
    "apply_modules",
    "ModuleError",
    "ModuleSpec",
    "ModuleBase",
    "parse_module",
    "ChocolateyModule",
    "ExeModule",
    "MsiModule",
    "IsoModule",
    "WinetricksModule",
    "PortableModule",
    "FilesModule",
    "ScriptModule",
    "PowerShellModule",
    "ContainerfileModule",
]
