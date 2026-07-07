"""Module system for Cage recipes.

Modules are first-class build directives that generate build steps.
Each module type implements a build() method that returns a list of BuildStep objects.
"""
from __future__ import annotations

from typing import Any

from .base import (
    ModuleBase, ModuleError, parse_module,
    ChocolateyModule, ExeModule, MsiModule, IsoModule,
    WinetricksModule, PortableModule, FilesModule, ScriptModule, PowerShellModule, ContainerfileModule,
)
from ..build_step import BuildStep


# ModuleSpec is an alias for ModuleBase for backward compatibility
ModuleSpec = ModuleBase


def collect_build_steps(modules: list[ModuleBase]) -> list[tuple[int, ModuleBase, list[BuildStep]]]:
    """Collect build steps from all modules in declaration order.
    
    Args:
        modules: List of parsed module instances
    
    Returns:
        List of (index, module, build_steps) tuples in declaration order
    """
    results = []
    for i, module in enumerate(modules):
        try:
            steps = module.build()
            results.append((i, module, steps))
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(f"modules[{i}] ({module.type}) build failed: {exc}") from exc
    return results


def generate_module_script(modules: list[ModuleBase]) -> str:
    """Generate a shell script that executes all modules in order.
    
    Each module logs "Running Module X/Y (Type)" before executing.
    
    Args:
        modules: List of parsed module instances
    
    Returns:
        Shell script as a string
    """
    if not modules:
        return ""
    
    lines = []
    total = len(modules)
    
    for i, module in enumerate(modules, 1):
        # Log module execution
        lines.append(f'echo "[cage] Running Module {i}/{total} ({module.type})"')
        
        # Generate build steps
        try:
            steps = module.build()
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(f"modules[{i-1}] ({module.type}) build failed: {exc}") from exc
        
        # Add build step commands
        for step in steps:
            lines.extend(step.to_shell_lines())
        
        lines.append("")  # Blank line between modules
    
    return "\n".join(lines)


__all__ = [
    "ModuleSpec",
    "ModuleBase",
    "ModuleError",
    "parse_module",
    "collect_build_steps",
    "generate_module_script",
    "BuildStep",
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
