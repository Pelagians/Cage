"""Chocolatey module expander.

Installs Chocolatey packages via the PowerShell wrapper.
This module implicitly depends on the powershell module for wrapper setup.
"""
from __future__ import annotations

import re
from typing import Any

from .base import ChocolateyModule, ModuleError


def expand_chocolatey(module: ChocolateyModule, index: int) -> dict[str, Any]:
    """Expand chocolatey module into dependencies + install steps.
    
    This module installs Chocolatey packages. It requires the powershell module
    to be present (either explicitly or will be auto-injected).
    """
    # Merge defaults with user-provided fields
    install = module.install or {}
    if module.defaults:
        default_install = module.defaults.get("install", {})
        if default_install:
            install = {**default_install, **install}
    
    packages = install.get("packages", [])
    if not isinstance(packages, list) or not packages:
        raise ModuleError(f"modules[{index}].install.packages must be a non-empty list")
    
    # Validate package names
    CHOCO_ARG_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_.+-]*|--?[A-Za-z0-9][A-Za-z0-9_.-]*)$")
    for pkg_index, pkg in enumerate(packages):
        if not CHOCO_ARG_RE.fullmatch(pkg):
            raise ModuleError(f"modules[{index}].install.packages[{pkg_index}] must use letters, numbers, dot, underscore, plus, or dash")
    
    # Separate install step per package (kind: choco)
    install_steps = []
    for pkg in packages:
        install_steps.append({
            "kind": "choco",
            "command": "install",
            "args": [pkg, "-y", "--no-progress"]
        })
    
    # Note: PowerShell wrapper setup is handled by the powershell module
    # which should be present in the recipe (either explicitly or auto-injected)
    
    return {
        "dependencies": [
            {"kind": "winetricks", "verbs": ["dotnet48"]}
        ],
        "install": install_steps,
    }
