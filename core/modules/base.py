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


@dataclass
class ChocolateyModule(ModuleBase):
    """Chocolatey package manager module."""
    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None  # Optional custom Chocolatey source URL
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for Chocolatey package installation."""
        if not self.install:
            raise ModuleError("chocolatey module requires 'install' field")
        
        packages = self.install.get("packages", [])
        if not packages:
            raise ModuleError("chocolatey module 'install.packages' cannot be empty")
        
        # Validate package names (alphanumeric with dots, underscores, plus, dashes)
        import re
        package_pattern = re.compile(r'^[a-zA-Z0-9._+\-]+$')
        for pkg in packages:
            if not package_pattern.match(pkg):
                raise ModuleError(f"chocolatey package name '{pkg}' must use letters, numbers, dot, underscore, plus, or dash")
        
        packages_str = " ".join(packages)
        
        # Install PowerShell wrapper first (required for Chocolatey installation)
        install_powershell = (
            'echo "Installing PowerShell wrapper for Wine..."; '
            'cd /tmp && '
            'curl -fsSL https://codeberg.org/Rustring/powershell-wrapper-for-wine/releases/download/v0.1.0/powershell-wrapper.tar.xz -o powershell-wrapper.tar.xz && '
            'tar -xJf powershell-wrapper.tar.xz && '
            'cd powershell-wrapper && '
            './install.sh && '
            'cd / && rm -rf /tmp/powershell-wrapper*'
        )
        
        # Install Chocolatey via PowerShell
        install_choco_ps = (
            "Set-ExecutionPolicy Bypass -Scope Process -Force; "
            "[System.Net.ServicePointManager]::SecurityProtocol = "
            "[System.Net.ServicePointManager]::SecurityProtocol -bor 3072; "
            "iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"
        )
        
        commands = [
            install_powershell,
            'echo "Installing Chocolatey package manager..."',
            f'powershell -Command "{install_choco_ps}"',
            'echo "Refreshing environment..."',
            'powershell -Command "refreshenv"',
            f'echo "  Installing Chocolatey packages: {packages_str}"',
            f"choco install {packages_str} -y --no-progress",
        ]
        
        return [BuildStep(
            commands=commands,
            description=f"Install Chocolatey: {packages_str}"
        )]


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
            description=f"Install EXE: {self.source}"
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
            description=f"Install MSI: {self.source}"
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
            description=f"Mount and run ISO: {self.source}"
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
            description=f"Install winetricks: {verbs_str}"
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
            description=f"Extract portable: {self.source} → {self.target}"
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
            description=f"Copy {len(self.mappings)} file(s)"
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
            working_dir=self.working_directory
        )]


@dataclass
class PowerShellModule(ModuleBase):
    """PowerShell wrapper module."""
    type: str = "powershell"
    mode: str | None = None  # "prebuilt", "build", or "corpowershell"
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for PowerShell setup."""
        mode = self.mode or "prebuilt"
        
        if mode == "prebuilt":
            commands = [
                'echo "  Setting up PowerShell (prebuilt mode)"',
                'echo "  PowerShell wrapper ready"',
            ]
        elif mode == "build":
            commands = [
                'echo "  Building PowerShell wrapper from source"',
                '# Build commands would go here',
            ]
        elif mode == "corpowershell":
            commands = [
                'echo "  Setting up PowerShell (corpowershell mode)"',
                '# Corpowershell setup commands would go here',
            ]
        else:
            raise ModuleError(f"powershell module invalid mode: {mode}")
        
        return [BuildStep(
            commands=commands,
            description=f"Setup PowerShell ({mode})"
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
            description=f"Execute {len(self.instructions)} containerfile instruction(s)"
        )]


def parse_module(data: dict[str, Any], index: int = 0) -> ModuleBase:
    """Parse a module definition from a dict.
    
    Args:
        data: Module definition dict with 'type' field
        index: Module index for error messages
    
    Returns:
        Parsed module instance
    
    Raises:
        ModuleError: If module definition is invalid
    """
    if not isinstance(data, dict):
        raise ModuleError(f"modules[{index}] must be a dict")
    
    module_type = data.get("type")
    if not module_type:
        raise ModuleError(f"modules[{index}] missing 'type' field")
    
    # Extract defaults if present
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ModuleError(f"modules[{index}] 'defaults' must be a dict")
    
    # Merge defaults with user data
    merged_data = ModuleBase(type=module_type, defaults=defaults).merge_defaults(data)
    
    # Parse based on module type
    if module_type == "chocolatey":
        return ChocolateyModule(
            type=module_type,
            defaults=defaults,
            install=merged_data.get("install"),
            source=merged_data.get("source"),
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
        return ScriptModule(
            type=module_type,
            defaults=defaults,
            command=merged_data.get("command"),
            working_directory=merged_data.get("working_directory"),
        )
    elif module_type == "powershell":
        return PowerShellModule(
            type=module_type,
            defaults=defaults,
            mode=merged_data.get("mode"),
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
    "PowerShellModule",
    "ContainerfileModule",
]
