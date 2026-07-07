"""Chocolatey module expander."""
from __future__ import annotations

import re
from typing import Any

from .base import ChocolateyModule, ModuleError


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


def expand_chocolatey(module: ChocolateyModule, index: int) -> dict[str, Any]:
    """Expand chocolatey module into dependencies + install steps."""
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
