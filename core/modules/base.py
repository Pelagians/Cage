"""Shared module parsing and build primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..build_step import BuildStep



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
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for this module.
        
        Returns a list of BuildStep objects that will be executed in order.
        Subclasses should override this method to provide module-specific build logic.
        """
        raise NotImplementedError(f"{self.type} module must implement build()")
    
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

    def capabilities(self) -> dict[str, str]:
        """Return capability slots provided by this module."""
        return {}


MODULE_FIELDS: dict[str, set[str]] = {
    "chocolatey": {"type", "defaults", "install", "packageSource"},
    "exe": {"type", "defaults", "source", "sha256", "silentArgs"},
    "msi": {"type", "defaults", "source", "sha256", "silentArgs"},
    "iso": {"type", "defaults", "source", "autorun"},
    "winetricks": {"type", "defaults", "verbs"},
    "portable": {"type", "defaults", "source", "target"},
    "files": {"type", "defaults", "mappings"},
    "script": {"type", "defaults", "command", "working_directory", "workingDirectory"},
}

FILES_MAPPING_FIELDS = {"source", "target", "sha256", "mode"}
FILES_MAPPING_MODES = {"copy", "merge"}


def _reject_unknown_module_fields(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ModuleError(f"unknown module field: {location}.{unknown[0]}")


def _required_str(data: dict[str, Any], key: str, location: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModuleError(f"{location}.{key} must be a non-empty string")
    return value


def _optional_str(data: dict[str, Any], key: str, location: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ModuleError(f"{location}.{key} must be a non-empty string when present")
    return value


def _string_list(value: Any, location: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ModuleError(f"{location} must be a list of non-empty strings")
    return value


def _validate_files_mappings(mappings: Any, location: str) -> None:
    if not isinstance(mappings, list) or not mappings:
        raise ModuleError(f"{location}.mappings must be a non-empty list")
    for mapping_index, mapping in enumerate(mappings):
        mapping_location = f"{location}.mappings[{mapping_index}]"
        if not isinstance(mapping, dict):
            raise ModuleError(f"{mapping_location} must be an object")
        _reject_unknown_module_fields(mapping, FILES_MAPPING_FIELDS, mapping_location)
        _required_str(mapping, "source", mapping_location)
        _required_str(mapping, "target", mapping_location)
        sha = _optional_str(mapping, "sha256", mapping_location)
        if sha is not None:
            import re
            if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
                raise ModuleError(f"{mapping_location}.sha256 must be 64 hexadecimal characters")
        mode = mapping.get("mode", "copy")
        if mode not in FILES_MAPPING_MODES:
            raise ModuleError(f"{mapping_location}.mode must be one of: " + ", ".join(sorted(FILES_MAPPING_MODES)))


def _validate_common_module_data(module_type: str, data: dict[str, Any], index: int) -> None:
    location = f"modules[{index}]"
    allowed = MODULE_FIELDS[module_type]
    _reject_unknown_module_fields(data, allowed, location)
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ModuleError(f"{location}.defaults must be a dict")
    _reject_unknown_module_fields(defaults, allowed - {"type", "defaults"}, f"{location}.defaults")

    if module_type in {"exe", "msi"}:
        _optional_str(data, "source", location)
        _optional_str(data, "sha256", location)
        silent_args = data.get("silentArgs")
        if silent_args is not None and not (
            isinstance(silent_args, str)
            or (isinstance(silent_args, list) and all(isinstance(item, str) for item in silent_args))
        ):
            raise ModuleError(f"{location}.silentArgs must be a string or list of strings")
    elif module_type == "iso":
        _optional_str(data, "source", location)
        if "autorun" in data and not isinstance(data["autorun"], bool):
            raise ModuleError(f"{location}.autorun must be a bool")
    elif module_type == "winetricks" and data.get("verbs") is not None:
        _string_list(data["verbs"], f"{location}.verbs")
    elif module_type == "portable":
        _optional_str(data, "source", location)
        _optional_str(data, "target", location)
    elif module_type == "files" and data.get("mappings") is not None:
        _validate_files_mappings(data["mappings"], location)
    elif module_type == "script":
        _optional_str(data, "command", location)
        _optional_str(data, "working_directory", location)
        _optional_str(data, "workingDirectory", location)
        if "working_directory" in data and "workingDirectory" in data:
            raise ModuleError(f"{location} cannot specify both working-directory spellings")
    elif module_type == "chocolatey":
        install = data.get("install")
        if install is not None and not isinstance(install, dict):
            raise ModuleError(f"{location}.install must be an object")
        _optional_str(data, "packageSource", location)



def parse_module(data: dict[str, Any], index: int = 0) -> ModuleBase:
    """Parse a module definition from a dict.
    
    This function takes a dictionary representing a module definition
    and returns the appropriate ModuleBase subclass instance.
    
    Args:
        data: Module definition dict with 'type' field
        index: Module index for error messages
    
    Returns:
        Appropriate ModuleBase subclass instance
    
    Raises:
        ModuleError: If module type is unknown or required fields are missing
    """
    from .chocolatey import ChocolateyModule
    from .exe import ExeModule
    from .msi import MsiModule
    from .iso import IsoModule
    from .winetricks import WinetricksModule
    from .portable import PortableModule
    from .files import FilesModule
    from .script import ScriptModule

    if not isinstance(data, dict):
        raise ModuleError(f"modules[{index}] must be an object")

    module_type = data.get("type")
    if not isinstance(module_type, str) or not module_type.strip():
        raise ModuleError(f"modules[{index}] missing 'type' field")
    
    # Extract defaults if present
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ModuleError(f"modules[{index}] 'defaults' must be a dict")
    
    # Merge defaults with user data
    merged_data = ModuleBase(type=module_type, defaults=defaults).merge_defaults(data)
    if module_type not in MODULE_FIELDS:
        raise ModuleError(f"modules[{index}] unknown module type: {module_type}")
    _validate_common_module_data(module_type, merged_data, index)
    
    # Parse based on module type
    if module_type == "chocolatey":
        module = ChocolateyModule(
            type=module_type,
            defaults=defaults,
            install=merged_data.get("install"),
            package_source=merged_data.get("packageSource"),
        )
        module.validate()
        return module
    elif module_type == "exe":
        return ExeModule(
            type=module_type,
            defaults=defaults,
            source=merged_data.get("source"),
            sha256=merged_data.get("sha256"),
            silentArgs=merged_data.get("silentArgs"),
        )
    elif module_type == "msi":
        return MsiModule(
            type=module_type,
            defaults=defaults,
            source=merged_data.get("source"),
            sha256=merged_data.get("sha256"),
            silentArgs=merged_data.get("silentArgs"),
        )
    elif module_type == "iso":
        return IsoModule(
            type=module_type,
            defaults=defaults,
            source=merged_data.get("source"),
            autorun=merged_data.get("autorun"),
        )
    elif module_type == "winetricks":
        return WinetricksModule(
            type=module_type,
            defaults=defaults,
            verbs=merged_data.get("verbs"),
        )
    elif module_type == "portable":
        return PortableModule(
            type=module_type,
            defaults=defaults,
            source=merged_data.get("source"),
            target=merged_data.get("target"),
        )
    elif module_type == "files":
        return FilesModule(
            type=module_type,
            defaults=defaults,
            mappings=merged_data.get("mappings"),
        )
    elif module_type == "script":
        working_directory = merged_data.get("working_directory", merged_data.get("workingDirectory"))
        return ScriptModule(
            type=module_type,
            defaults=defaults,
            command=merged_data.get("command"),
            working_directory=working_directory,
        )
    else:
        raise ModuleError(f"modules[{index}] unknown module type: {module_type}")


__all__ = [
    "ModuleError",
    "ModuleBase",
    "parse_module",
]
