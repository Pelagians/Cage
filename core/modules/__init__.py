"""Module expansion registry and main entry point."""
from __future__ import annotations

from typing import Any

from .base import ModuleSpec, ModuleError
from .chocolatey import expand_chocolatey
from .exe import expand_exe
from .msi import expand_msi
from .iso import expand_iso
from .winetricks import expand_winetricks
from .portable import expand_portable
from .script import expand_script
from .containerfile import expand_containerfile


# Registry of module expanders
EXPANDERS = {
    "chocolatey": expand_chocolatey,
    "exe": expand_exe,
    "msi": expand_msi,
    "iso": expand_iso,
    "winetricks": expand_winetricks,
    "portable": expand_portable,
    "script": expand_script,
    "containerfile": expand_containerfile,
}


def apply_modules(data: dict[str, Any]) -> dict[str, Any]:
    """Expand all modules and merge into data dict.
    
    Modifies data in place, adding to:
    - data["dependencies"]
    - data["install"]
    - data["filesystem"]
    - data["registry"]
    - data["compatibility"]
    - data["sources"]
    - data["exports"]
    - data["provenance"]["moduleExpansions"]
    
    Returns the modified data dict.
    """
    modules_data = data.get("modules", [])
    if not modules_data:
        return data
    
    dependencies: list[dict[str, Any]] = data.get("dependencies", [])
    install: list[dict[str, Any]] = data.get("install", [])
    filesystem: list[dict[str, Any]] = data.get("filesystem", [])
    registry: list[dict[str, Any]] = data.get("registry", [])
    compatibility: dict[str, Any] = data.get("compatibility", {})
    sources: list[dict[str, Any]] = data.get("sources", [])
    exports: list[dict[str, Any]] = data.get("exports", [])
    provenance_expansions: list[dict[str, Any]] = []
    
    for index, module_data in enumerate(modules_data):
        module = ModuleSpec.from_dict(module_data, index)
        expander = EXPANDERS.get(module.type)
        if not expander:
            raise ModuleError(f"Unknown module type: {module.type}")
        
        expansion = expander(module, index)
        
        # Merge dependencies
        for dep in expansion.get("dependencies", []):
            dependencies.append(dep)
        
        # Merge install steps
        for step in expansion.get("install", []):
            install.append(step)
        
        # Merge filesystem mappings
        for mapping in expansion.get("filesystem", []):
            filesystem.append(mapping)
        
        # Merge registry tweaks
        for tweak in expansion.get("registry", []):
            registry.append(tweak)
        
        # Merge compatibility settings
        if "compatibility" in expansion:
            compatibility.update(expansion["compatibility"])
        
        # Merge sources
        for source in expansion.get("sources", []):
            sources.append(source)
        
        # Merge exports
        for export in expansion.get("exports", []):
            exports.append(export)
        
        # Record provenance
        provenance_expansions.append({
            "type": module.type,
            "install": module.install,
            "schemaVersion": "cage.module-expansion/v0",
            "injectedDependencies": expansion.get("dependencies", []),
            "injectedInstallStepCount": len(expansion.get("install", [])),
        })
    
    # Update data dict
    if dependencies:
        data["dependencies"] = dependencies
    if install:
        data["install"] = install
    if filesystem:
        data["filesystem"] = filesystem
    if registry:
        data["registry"] = registry
    if compatibility:
        data["compatibility"] = compatibility
    if sources:
        data["sources"] = sources
    if exports:
        data["exports"] = exports
    if provenance_expansions:
        if "provenance" not in data:
            data["provenance"] = {}
        data["provenance"]["moduleExpansions"] = provenance_expansions
    
    return data


__all__ = [
    "ModuleSpec",
    "ModuleError",
    "apply_modules",
    "EXPANDERS",
]
