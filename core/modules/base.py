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
    "chocolatey": {"type", "defaults", "install", "source", "bootstrap"},
    "exe": {"type", "defaults", "source", "sha256", "silentArgs"},
    "msi": {"type", "defaults", "source", "sha256", "silentArgs"},
    "iso": {"type", "defaults", "source", "autorun"},
    "winetricks": {"type", "defaults", "verbs"},
    "portable": {"type", "defaults", "source", "target", "config"},
    "files": {"type", "defaults", "mappings"},
    "script": {"type", "defaults", "command", "working_directory", "workingDirectory"},
    "powershell-wrapper": {"type", "defaults", "version", "wrapperVersion"},
    "containerfile": {"type", "defaults", "instructions"},
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
        _optional_str(mapping, "sha256", mapping_location)
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
        _optional_str(data, "config", location)
    elif module_type == "files" and data.get("mappings") is not None:
        _validate_files_mappings(data["mappings"], location)
    elif module_type == "script":
        _optional_str(data, "command", location)
        _optional_str(data, "working_directory", location)
        _optional_str(data, "workingDirectory", location)
    elif module_type == "powershell-wrapper":
        _optional_str(data, "version", location)
        _optional_str(data, "wrapperVersion", location)
    elif module_type == "containerfile" and data.get("instructions") is not None:
        _string_list(data["instructions"], f"{location}.instructions")
    elif module_type == "chocolatey":
        install = data.get("install")
        if install is not None and not isinstance(install, dict):
            raise ModuleError(f"{location}.install must be an object")
        _optional_str(data, "source", location)
        _optional_str(data, "bootstrap", location)


@dataclass
class ExeModule(ModuleBase):
    """EXE installer module."""
    type: str = "exe"
    source: str | None = None
    sha256: str | None = None
    silentArgs: str | list[str] | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for EXE installation."""
        if not self.source:
            raise ModuleError("exe module requires 'source' field")
        
        # Build the silent args string
        args_str = ""
        if self.silentArgs:
            if isinstance(self.silentArgs, list):
                args_str = " ".join(self.silentArgs)
            else:
                args_str = self.silentArgs
        
        commands = [
            f'echo "  Installing {self.source}"',
            f"wine {self.source} {args_str}".strip(),
        ]
        
        return [BuildStep(
            commands=commands,
            description=f"Install EXE: {self.source}",
            kind="wine-run",
        )]


@dataclass
class MsiModule(ModuleBase):
    """MSI installer module."""
    type: str = "msi"
    source: str | None = None
    sha256: str | None = None
    silentArgs: str | list[str] | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for MSI installation."""
        if not self.source:
            raise ModuleError("msi module requires 'source' field")
        
        # Build the silent args string
        args_str = "/qn"  # Default silent install
        if self.silentArgs:
            if isinstance(self.silentArgs, list):
                args_str = " ".join(["/qn"] + self.silentArgs)
            else:
                args_str = f"/qn {self.silentArgs}"
        
        commands = [
            f'echo "  Installing MSI: {self.source}"',
            f"msiexec /i {self.source} {args_str}".strip(),
        ]
        
        return [BuildStep(
            commands=commands,
            description=f"Install MSI: {self.source}",
            kind="wine-msiexec",
        )]


@dataclass
class IsoModule(ModuleBase):
    """ISO mount and run module."""
    type: str = "iso"
    source: str | None = None
    autorun: bool | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for ISO mounting and execution."""
        if not self.source:
            raise ModuleError("iso module requires 'source' field")
        
        commands = [
            f'echo "  Mounting ISO: {self.source}"',
            f"MOUNT_POINT=$(mktemp -d)",
            f"mount -o loop {self.source} $MOUNT_POINT",
        ]
        
        if self.autorun:
            commands.extend([
                'echo "  Running autorun"',
                "wine $MOUNT_POINT/setup.exe || wine $MOUNT_POINT/autorun.exe",
            ])
        
        commands.extend([
            "umount $MOUNT_POINT",
            "rmdir $MOUNT_POINT",
        ])
        
        return [BuildStep(
            commands=commands,
            description=f"Mount and run ISO: {self.source}",
            kind="raw-shell",
        )]


@dataclass
class WinetricksModule(ModuleBase):
    """Winetricks verbs module."""
    type: str = "winetricks"
    verbs: list[str] | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for winetricks verbs."""
        if not self.verbs:
            raise ModuleError("winetricks module requires 'verbs' field")
        
        verbs_str = " ".join(self.verbs)
        commands = [
            f'echo "  Installing winetricks verbs: {verbs_str}"',
            f"winetricks -q {verbs_str}",
        ]
        
        return [BuildStep(
            commands=commands,
            description=f"Install winetricks: {verbs_str}",
            kind="wine-run",
        )]


@dataclass
class PortableModule(ModuleBase):
    """Portable app staging module."""
    type: str = "portable"
    source: str | None = None
    target: str | None = None
    config: str | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for portable app extraction."""
        if not self.source:
            raise ModuleError("portable module requires 'source' field")
        if not self.target:
            raise ModuleError("portable module requires 'target' field")
        
        commands = [
            f'echo "  Extracting portable app to {self.target}"',
            f"mkdir -p {self.target}",
            f"unzip -o {self.source} -d {self.target}",
        ]
        
        if self.config:
            commands.append(f'echo "  Applying config: {self.config}"')
            # Config application would be handled here
        
        return [BuildStep(
            commands=commands,
            description=f"Extract portable: {self.source} → {self.target}",
            kind="extract",
        )]


@dataclass
class FilesModule(ModuleBase):
    """File copying module."""
    type: str = "files"
    mappings: list[dict[str, Any]] | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for file copying."""
        if not self.mappings:
            raise ModuleError("files module requires 'mappings' field")
        
        commands = []
        for mapping in self.mappings:
            source = mapping.get("source")
            target = mapping.get("target")
            if not source or not target:
                raise ModuleError("files module mapping requires 'source' and 'target'")
            
            commands.append(f'echo "  Copying {source} → {target}"')
            commands.append(f"mkdir -p $(dirname {target})")
            commands.append(f"cp -r {source} {target}")
        
        return [BuildStep(
            commands=commands,
            description=f"Copy {len(self.mappings)} file(s)",
            kind="copy-tree",
        )]


@dataclass
class ScriptModule(ModuleBase):
    """Script execution module."""
    type: str = "script"
    command: str | None = None
    working_directory: str | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for script execution."""
        if not self.command:
            raise ModuleError("script module requires 'command' field")
        
        commands = [
            f'echo "  Running script: {self.command[:50]}..."',
            self.command,
        ]
        
        return [BuildStep(
            commands=commands,
            description=f"Run script: {self.command[:50]}...",
            working_dir=self.working_directory,
            kind="raw-shell",
            unsafe=True,
            metadata={"escapeHatch": "script"},
        )]


@dataclass
class ContainerfileModule(ModuleBase):
    """Containerfile escape hatch module."""
    type: str = "containerfile"
    instructions: list[str] | None = None
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for raw containerfile instructions."""
        if not self.instructions:
            raise ModuleError("containerfile module requires 'instructions' field")
        
        commands = [
            'echo "  Executing containerfile instructions"',
        ]
        commands.extend(self.instructions)
        
        return [BuildStep(
            commands=commands,
            description=f"Execute {len(self.instructions)} containerfile instruction(s)",
            kind="raw-shell",
            unsafe=True,
            metadata={"escapeHatch": "containerfile"},
        )]


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
    from .powershell_wrapper import PowerShellWrapperModule
    
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
    if module_type == "powershell":
        raise ModuleError(
            f"modules[{index}] module type 'powershell' was renamed to 'powershell-wrapper'"
        )
    if module_type not in MODULE_FIELDS:
        raise ModuleError(f"modules[{index}] unknown module type: {module_type}")
    _validate_common_module_data(module_type, merged_data, index)
    
    # Parse based on module type
    if module_type == "chocolatey":
        return ChocolateyModule(
            type=module_type,
            defaults=defaults,
            install=merged_data.get("install"),
            source=merged_data.get("source"),
            bootstrap=merged_data.get("bootstrap", "cfw-v0.5c.755-choco-2.6.0-dotnet481-r2"),
        )
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
            config=merged_data.get("config"),
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
    elif module_type == "powershell":
        raise ModuleError(
            f"modules[{index}] module type 'powershell' was renamed to 'powershell-wrapper'"
        )
    elif module_type == "powershell-wrapper":
        return PowerShellWrapperModule(
            type=module_type,
            defaults=defaults,
            version=merged_data.get("version", "7"),
            wrapper_version=merged_data.get("wrapperVersion", "v4.2.0"),
        )
    elif module_type == "containerfile":
        return ContainerfileModule(
            type=module_type,
            defaults=defaults,
            instructions=merged_data.get("instructions"),
        )
    else:
        raise ModuleError(f"modules[{index}] unknown module type: {module_type}")


__all__ = [
    "ModuleError",
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
    "ContainerfileModule",
]
