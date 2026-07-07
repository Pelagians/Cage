"""Module expansion system for Cage recipes.

Modules allow recipes to express high-level intent (install this EXE, use Chocolatey,
apply winetricks verbs) and have Cage automatically expand them into the low-level
dependencies, install steps, filesystem mappings, and registry tweaks needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class ModuleError(Exception):
    """Raised when a module definition is invalid."""
    pass


@dataclass
class ModuleSpec:
    """Specification for a single module in a recipe."""
    type: str
    install: dict[str, Any] | None = None
    source: str | None = None
    sha256: str | None = None
    silentArgs: str | list[str] | None = None
    verbs: list[str] | None = None
    target: str | None = None
    command: str | None = None
    config: str | None = None
    autorun: bool | None = None
    # containerfile module fields
    dependencies: list[dict[str, Any]] | None = None
    filesystem: list[dict[str, Any]] | None = None
    registry: list[dict[str, Any]] | None = None
    compatibility: dict[str, Any] | None = None
    sources: list[dict[str, Any]] | None = None
    exports: list[dict[str, Any]] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> ModuleSpec:
        """Parse a module definition from recipe dict."""
        if not isinstance(data, dict):
            raise ModuleError(f"modules[{index}] must be a dict")
        
        module_type = data.get("type")
        if not isinstance(module_type, str) or not module_type:
            raise ModuleError(f"modules[{index}].type must be a non-empty string")
        
        allowed_types = {"chocolatey", "exe", "msi", "iso", "winetricks", "portable", "script", "containerfile"}
        if module_type not in allowed_types:
            raise ModuleError(
                f"modules[{index}].type must be one of: {', '.join(sorted(allowed_types))}"
            )
        
        return cls(
            type=module_type,
            install=data.get("install"),
            source=data.get("source"),
            sha256=data.get("sha256"),
            silentArgs=data.get("silentArgs"),
            verbs=data.get("verbs"),
            target=data.get("target"),
            command=data.get("command"),
            config=data.get("config"),
            autorun=data.get("autorun"),
            # containerfile fields
            dependencies=data.get("dependencies"),
            filesystem=data.get("filesystem"),
            registry=data.get("registry"),
            compatibility=data.get("compatibility"),
            sources=data.get("sources"),
            exports=data.get("exports"),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert back to dict for serialization."""
        result = {"type": self.type}
        if self.install is not None:
            result["install"] = self.install
        if self.source is not None:
            result["source"] = self.source
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        if self.silentArgs is not None:
            result["silentArgs"] = self.silentArgs
        if self.verbs is not None:
            result["verbs"] = self.verbs
        if self.target is not None:
            result["target"] = self.target
        if self.command is not None:
            result["command"] = self.command
        if self.config is not None:
            result["config"] = self.config
        if self.autorun is not None:
            result["autorun"] = self.autorun
        # containerfile fields
        if self.dependencies is not None:
            result["dependencies"] = self.dependencies
        if self.filesystem is not None:
            result["filesystem"] = self.filesystem
        if self.registry is not None:
            result["registry"] = self.registry
        if self.compatibility is not None:
            result["compatibility"] = self.compatibility
        if self.sources is not None:
            result["sources"] = self.sources
        if self.exports is not None:
            result["exports"] = self.exports
        return result
