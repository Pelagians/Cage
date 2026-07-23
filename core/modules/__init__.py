"""Module system for Cage recipes.

Modules are first-class build directives that generate build steps.
Each module type implements a build() method that returns a list of BuildStep objects.
"""
from __future__ import annotations

from collections.abc import Collection
from typing import Any

from .base import (
    ModuleBase, ModuleError, parse_module,
    ExeModule, MsiModule, IsoModule,
    WinetricksModule, PortableModule, FilesModule, ScriptModule, ContainerfileModule,
)
from .chocolatey import ChocolateyModule
from ..build_step import BuildStep


# ModuleSpec is an alias for ModuleBase for backward compatibility
ModuleSpec = ModuleBase


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


def generate_module_script(
    modules: list[ModuleBase],
    *,
    include_kinds: Collection[str] | None = None,
    exclude_kinds: Collection[str] | None = None,
    phase_label: str | None = None,
) -> str:
    """Generate shell for selected module steps while preserving declaration order.

    ``prefix-seed`` steps are rendered separately before Wine initialization.
    Filtering is generic so future modules can contribute other pipeline-owned
    step kinds without duplicating module implementations.
    """
    if not modules:
        return ""

    include = set(include_kinds or ())
    exclude = set(exclude_kinds or ())
    lines: list[str] = []
    total = len(modules)

    for i, module in enumerate(modules, 1):
        try:
            steps = module.build()
        except ModuleError:
            raise
        except Exception as exc:
            raise ModuleError(f"modules[{i-1}] ({module.type}) build failed: {exc}") from exc

        selected = [
            step for step in steps
            if (not include or step.kind in include) and step.kind not in exclude
        ]
        if not selected:
            continue

        label = f" — {phase_label}" if phase_label else ""
        lines.append(f'echo "[cage] Running Module {i}/{total} ({module.type}){label}"')
        for step in selected:
            lines.extend(step.to_shell_lines())
        lines.append("")

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
    "ContainerfileModule",
]
