"""Module expansion for Cage recipes.

Modules are high-level installation intents that expand into low-level
dependencies, install steps, and configuration. This keeps recipes simple
while allowing modules to handle Wine-specific complexity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ModuleError(ValueError):
    pass


@dataclass
class ModuleSpec:
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


# PowerShell wrapper setup for Chocolatey
CHOCOLATEY_SETUP_COMMAND = (
    'set -eu; '
    'pwsh="$WINEPREFIX/drive_c/Program Files/PowerShell/7/pwsh.exe"; '
    'wrapper="$WINEPREFIX/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"; '
    'choco="$WINEPREFIX/drive_c/ProgramData/chocolatey/bin/choco.exe"; '
    'if [ -f "$choco" ] && [ -f "$wrapper" ]; then exit 0; fi; '
    'if ! command -v git >/dev/null 2>&1; then '
    'apt-get update -qq && apt-get install -y -qq --no-install-recommends git gcc libc-dev pkg-config gcc-mingw-w64-x86-64; '
    'fi; '
    'if ! command -v cargo >/dev/null 2>&1; then '
    'curl -fsSL https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal -q 2>/dev/null; '
    '. "$HOME/.cargo/env"; '
    'fi; '
    'if command -v rustup >/dev/null; then rustup target add x86_64-pc-windows-gnu; fi; '
    'repo="$WINEPREFIX/drive_c/cage/powershell-wrapper-for-wine"; '
    'rm -rf "$repo"; '
    'mkdir -p "$(dirname "$repo")"; '
    'git clone --depth=1 https://codeberg.org/Synchro/powershell-wrapper-for-wine.git "$repo"; '
    '(cd "$repo" && cargo run --package xtask -- build --arch 64); '
    'mkdir -p "$(dirname "$wrapper")"; '
    'cp "$repo"/target/x86_64-pc-windows-gnu/release/*.exe "$wrapper"; '
    'wine "$WINEPREFIX/drive_c/Program Files/PowerShell/7/pwsh.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command '
    '"$env:chocolateyVersion = \'1.4.0\'; iex ((New-Object System.Net.WebClient).DownloadString(\'https://community.chocolatey.org/install.ps1\'))"'
)


def _expand_chocolatey(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand chocolatey module into dependencies + install steps."""
    install = module.install or {}
    packages = install.get("packages", [])
    if not isinstance(packages, list) or not packages:
        raise ModuleError(f"modules[{index}].install.packages must be a non-empty list")
    
    # Validate package names
    import re
    CHOCO_ARG_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_.+-]*|--?[A-Za-z0-9][A-Za-z0-9_.-]*)$")
    for pkg_index, pkg in enumerate(packages):
        if not CHOCO_ARG_RE.fullmatch(pkg):
            raise ModuleError(f"modules[{index}].install.packages[{pkg_index}] must use letters, numbers, dot, underscore, plus, or dash")
    
    # Setup script (runs once)
    setup_step = {"kind": "script", "command": CHOCOLATEY_SETUP_COMMAND}
    
    # Separate install step per package (kind: choco)
    install_steps = [setup_step]
    for pkg in packages:
        install_steps.append({
            "kind": "choco",
            "command": "install",
            "args": [pkg, "-y", "--no-progress"]
        })
    
    return {
        "dependencies": [
            {"kind": "winetricks", "verbs": ["dotnet48", "win10", "powershell_core"]}
        ],
        "install": install_steps,
    }


def _expand_exe(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand exe module into install steps."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for exe")
    
    args = []
    if module.silentArgs:
        if isinstance(module.silentArgs, str):
            args = module.silentArgs.split()
        else:
            args = module.silentArgs
    
    install_step = {
        "kind": "exe",
        "source": module.source,
        "args": args,
    }
    if module.sha256:
        install_step["sha256"] = module.sha256
    
    result = {"install": [install_step]}
    
    # Optional config overlay
    if module.config:
        result["filesystem"] = [
            {"source": module.config, "target": f"C:/config/{module.type}-config"}
        ]
    
    return result


def _expand_msi(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand msi module into install steps."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for msi")
    
    args = []
    if module.silentArgs:
        if isinstance(module.silentArgs, str):
            args = module.silentArgs.split()
        else:
            args = module.silentArgs
    else:
        args = ["/qn", "/norestart"]  # Default silent install
    
    install_step = {
        "kind": "msi",
        "source": module.source,
        "args": args,
    }
    if module.sha256:
        install_step["sha256"] = module.sha256
    
    return {"install": [install_step]}


def _expand_iso(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand iso module into install steps."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for iso")
    
    # ISO mounting and autorun script
    script = f"""set -eu
iso_path="$WINEPREFIX/drive_c/cage/iso-{index}.iso"
# Stage ISO (assumes source is already staged)
mount_point="$WINEPREFIX/drive_c/cage/iso-mount-{index}"
mkdir -p "$mount_point"
# Try to mount (may need root or fuseiso)
if command -v mount >/dev/null 2>&1; then
    mount -o loop,ro "$iso_path" "$mount_point" || true
fi
# Run setup if autorun enabled
if [ {str(module.autorun).lower()} = "true" ] && [ -f "$mount_point/setup.exe" ]; then
    wine "$mount_point/setup.exe" /S || wine "$mount_point/setup.exe" /qn || true
fi
# Cleanup
umount "$mount_point" 2>/dev/null || true
rmdir "$mount_point" 2>/dev/null || true
"""
    
    install_step = {
        "kind": "script",
        "command": script,
    }
    
    return {"install": [install_step]}


def _expand_winetricks(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand winetricks module into dependencies."""
    if not module.verbs:
        raise ModuleError(f"modules[{index}].verbs must be a non-empty list")
    
    return {
        "dependencies": [
            {"kind": "winetricks", "verbs": module.verbs}
        ]
    }


def _expand_portable(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand portable module into install steps."""
    if not module.source:
        raise ModuleError(f"modules[{index}].source is required for portable")
    if not module.target:
        raise ModuleError(f"modules[{index}].target is required for portable")
    
    install_step = {
        "kind": "portable",
        "source": module.source,
        "target": module.target,
    }
    if module.sha256:
        install_step["sha256"] = module.sha256
    
    return {"install": [install_step]}


def _expand_script(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand script module into install steps."""
    if not module.command:
        raise ModuleError(f"modules[{index}].command is required for script")
    
    return {
        "install": [
            {"kind": "script", "command": module.command}
        ]
    }


def _expand_containerfile(module: ModuleSpec, index: int) -> dict[str, Any]:
    """Expand containerfile module by merging raw fields into recipe.
    
    This module type allows complex/odd-fix recipes to use raw fields
    (dependencies, install, filesystem, registry, compatibility, sources, exports)
    nested inside the module, similar to BlueBuild's approach.
    
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


EXPANDERS = {
    "chocolatey": _expand_chocolatey,
    "exe": _expand_exe,
    "msi": _expand_msi,
    "iso": _expand_iso,
    "winetricks": _expand_winetricks,
    "portable": _expand_portable,
    "script": _expand_script,
    "containerfile": _expand_containerfile,
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
