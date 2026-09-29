"""Module system for Cage recipes.

Modules are first-class build directives that generate build steps.
Each module type implements a build() method that returns a list of BuildStep objects.
"""
from __future__ import annotations


from .base import (
    ModuleBase, ModuleError, parse_module,
)
from .chocolatey import ChocolateyModule
from ..build_step import BuildStep


from .install import InstallModule
from .registry import RegistryModule
from .extract import ExtractModule
from .check import CheckModule
from .dll import DllModule
from .iso import IsoModule
from .winetricks import WinetricksModule
from .portable import PortableModule
from .files import FilesModule
from .script import ScriptModule


def collect_build_steps(modules: list[ModuleBase]) -> list[tuple[int, ModuleBase, list[BuildStep]]]:
    """Collect build steps from all modules in declaration order."""
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


__all__ = [
    "ModuleBase",
    "ModuleError",
    "parse_module",
    "collect_build_steps",
    "BuildStep",
    "ChocolateyModule",
    "InstallModule",
    "RegistryModule",
    "ExtractModule",
    "CheckModule",
    "DllModule",
    "IsoModule",
    "WinetricksModule",
    "PortableModule",
    "FilesModule",
    "ScriptModule",
]
