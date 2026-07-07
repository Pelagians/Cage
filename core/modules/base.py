"""Module expansion system for Cage recipes.

Modules allow recipes to express high-level intent (install this EXE, use Chocolatey,
apply winetricks verbs) and have Cage automatically expand them into the low-level
dependencies, install steps, filesystem mappings, and registry tweaks needed.

Module composition: Modules can nest other modules via the `modules` field, allowing
reusable module definitions with defaults.

Module defaults: Each module type can define default values that are merged with
user-provided fields before expansion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ModuleError(Exception):
    """Raised when a module definition is invalid."""
    pass


@dataclass
class ModuleBase:
    """Base class for all module types."""
    type: str
    defaults: dict[str, Any] = field(default_factory=dict)
    
    def merge_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        """Merge defaults with user-provided data (user data takes precedence)."""
        if not self.defaults:
            return data
        merged = {**self.defaults, **data}
        return merged
    
    def to_dict(self) -> dict[str, Any]:
        """Convert module back to dict for serialization."""
        result = {"type": self.type}
        if self.defaults:
            result["defaults"] = self.defaults
        # Add all non-None fields from the dataclass
        for field_name in self.__dataclass_fields__:
            if field_name in ("type", "defaults"):
                continue
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = value
        return result


@dataclass
class ChocolateyModule(ModuleBase):
    """Chocolatey package manager module."""
    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None  # Optional custom Chocolatey source URL


@dataclass
class ExeModule(ModuleBase):
    """EXE installer module."""
    type: str = "exe"
    source: str | None = None
    sha256: str | None = None
    silentArgs: str | list[str] | None = None


@dataclass
class MsiModule(ModuleBase):
    """MSI installer module."""
    type: str = "msi"
    source: str | None = None
    sha256: str | None = None
    silentArgs: str | list[str] | None = None


@dataclass
class IsoModule(ModuleBase):
    """ISO mount and run module."""
    type: str = "iso"
    source: str | None = None
    autorun: bool | None = None


@dataclass
class WinetricksModule(ModuleBase):
    """Winetricks verbs module."""
    type: str = "winetricks"
    verbs: list[str] | None = None


@dataclass
class PortableModule(ModuleBase):
    """Portable app staging module."""
    type: str = "portable"
    source: str | None = None
    target: str | None = None
    config: str | None = None


@dataclass
class FilesModule(ModuleBase):
    """Files mapping module for copying files/directories to container."""
    type: str = "files"
    mappings: list[dict[str, Any]] | None = None


@dataclass
class ScriptModule(ModuleBase):
    """Arbitrary bash script module."""
    type: str = "script"
    command: str | None = None


@dataclass
class PowerShellModule(ModuleBase):
    """PowerShell wrapper module for running Windows PowerShell scripts under Wine."""
    type: str = "powershell"
    mode: str | None = None  # "prebuilt" (default), "build", or "core"


@dataclass
class PowerShellModule(ModuleBase):
    """PowerShell wrapper module for Wine.
    
    Sets up PowerShell execution environment in Wine prefix using the
    Rust-based PowerShell wrapper from Codeberg.
    
    Fields:
        mode: "prebuilt" (download binary), "build" (build from source), or "core" (PowerShell Core only)
        version: Version of prebuilt binary to download (default: "1.0.0")
    """
    mode: str | None = None
    version: str | None = None


@dataclass
class ContainerfileModule(ModuleBase):
    """Raw fields passthrough module for complex recipes."""
    type: str = "containerfile"
    dependencies: list[dict[str, Any]] | None = None
    install: list[dict[str, Any]] | None = None
    filesystem: list[dict[str, Any]] | None = None
    registry: list[dict[str, Any]] | None = None
    compatibility: dict[str, Any] | None = None
    sources: list[dict[str, Any]] | None = None
    exports: list[dict[str, Any]] | None = None
    # Module composition: can nest other modules
    modules: list[dict[str, Any]] | None = None


# Union type for all modules
ModuleSpec = (
    ChocolateyModule | ExeModule | MsiModule | IsoModule |
    WinetricksModule | PortableModule | ScriptModule | PowerShellModule | ContainerfileModule
)


def parse_module(data: dict[str, Any], index: int) -> ModuleSpec:
    """Parse a module definition from recipe dict into the appropriate ModuleSpec."""
    if not isinstance(data, dict):
        raise ModuleError(f"modules[{index}] must be a dict")
    
    module_type = data.get("type")
    if not isinstance(module_type, str) or not module_type:
        raise ModuleError(f"modules[{index}].type must be a non-empty string")
    
    # Extract defaults if present
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ModuleError(f"modules[{index}].defaults must be a dict")
    
    # Parse based on type
    if module_type == "chocolatey":
        return ChocolateyModule(
            defaults=defaults,
            install=data.get("install"),
            source=data.get("source"),
        )
    elif module_type == "exe":
        return ExeModule(
            defaults=defaults,
            source=data.get("source"),
            sha256=data.get("sha256"),
            silentArgs=data.get("silentArgs"),
        )
    elif module_type == "msi":
        return MsiModule(
            defaults=defaults,
            source=data.get("source"),
            sha256=data.get("sha256"),
            silentArgs=data.get("silentArgs"),
        )
    elif module_type == "iso":
        return IsoModule(
            defaults=defaults,
            source=data.get("source"),
            autorun=data.get("autorun"),
        )
    elif module_type == "winetricks":
        return WinetricksModule(
            defaults=defaults,
            verbs=data.get("verbs"),
        )
    elif module_type == "portable":
        return PortableModule(
            type=module_type,
            defaults=defaults,
            source=data.get("source"),
            target=data.get("target"),
            config=data.get("config"),
        )
    elif module_type == "files":
        return FilesModule(
            type=module_type,
            defaults=defaults,
            mappings=data.get("mappings"),
        )
    elif module_type == "script":
        return ScriptModule(
            defaults=defaults,
            command=data.get("command"),
        )
    elif module_type == "powershell":
        return PowerShellModule(
            type=module_type,
            defaults=defaults,
            mode=data.get("mode"),
            version=data.get("version"),
        )
    elif module_type == "containerfile":
        return ContainerfileModule(
            defaults=defaults,
            dependencies=data.get("dependencies"),
            install=data.get("install"),
            filesystem=data.get("filesystem"),
            registry=data.get("registry"),
            compatibility=data.get("compatibility"),
            sources=data.get("sources"),
            exports=data.get("exports"),
            modules=data.get("modules"),
        )
    else:
        allowed_types = {"chocolatey", "exe", "msi", "iso", "winetricks", "portable", "script", "powershell", "containerfile"}
        raise ModuleError(
            f"modules[{index}].type must be one of: {', '.join(sorted(allowed_types))}"
        )
