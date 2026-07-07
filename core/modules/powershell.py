"""PowerShell module expander.

Handles PowerShell wrapper setup for Wine, enabling PowerShell script execution
within Wine prefixes. Supports prebuilt binaries or building from source.
"""
from __future__ import annotations

import re
from typing import Any

from .base import PowerShellModule, ModuleError


# PowerShell wrapper repository
POWERSHELL_WRAPPER_REPO = "https://codeberg.org/Synchro/powershell-wrapper-for-wine.git"

# Prebuilt binary URL template (version will be substituted)
PREBUILT_URL_TEMPLATE = "https://github.com/pelagians/powershell-wrapper-for-wine/releases/download/v{version}/powershell-wrapper-x86_64.exe"

# Default wrapper version
DEFAULT_WRAPPER_VERSION = "1.0.0"

# Build command for wrapper (requires Rust toolchain)
BUILD_WRAPPER_COMMAND = """set -eu
repo="$WINEPREFIX/drive_c/cage/powershell-wrapper-for-wine"
rm -rf "$repo"
mkdir -p "$(dirname "$repo")"
git clone --depth=1 {repo_url} "$repo"
cd "$repo"
cargo build --release --target x86_64-pc-windows-gnu
"""

# Download command for prebuilt binary
DOWNLOAD_WRAPPER_COMMAND = """set -eu
wrapper_dir="$WINEPREFIX/drive_c/cage/powershell-wrapper"
mkdir -p "$wrapper_dir"
curl -fsSL -o "$wrapper_dir/powershell-wrapper.exe" "{url}"
chmod +x "$wrapper_dir/powershell-wrapper.exe"
"""

# Copy wrapper to system32 location
COPY_WRAPPER_COMMAND = """set -eu
wrapper_src="$WINEPREFIX/drive_c/cage/powershell-wrapper/powershell-wrapper.exe"
wrapper_dst="$WINEPREFIX/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
if [ ! -f "$wrapper_src" ]; then
  wrapper_src="$WINEPREFIX/drive_c/cage/powershell-wrapper-for-wine/target/x86_64-pc-windows-gnu/release/powershell-wrapper.exe"
fi
mkdir -p "$(dirname "$wrapper_dst")"
cp "$wrapper_src" "$wrapper_dst"
"""

# Install Chocolatey using PietJankbal's Wine-optimized script
# This script works around Wine's limitations with the standard Chocolatey installer
INSTALL_CHOCOLATEY_COMMAND = """set -eu
curl -fsSL -o "$WINEPREFIX/drive_c/cage/choc_install.ps1" \\
  "https://raw.githubusercontent.com/PietJankbal/Chocolatey-for-wine/main/choc_install.ps1"
wine "$WINEPREFIX/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe" \\
  -NoLogo -NoProfile -ExecutionPolicy Bypass \\
  -File "C:\\cage\\choc_install.ps1"
"""

# Cleanup build artifacts
CLEANUP_BUILD_COMMAND = """set -eu
rm -rf "$WINEPREFIX/drive_c/cage/powershell-wrapper-for-wine"
rm -rf "$WINEPREFIX/drive_c/cage/powershell-wrapper"
"""

# Install build dependencies (Rust toolchain)
INSTALL_BUILD_DEPS_COMMAND = """set -eu
if ! command -v cargo >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends git gcc libc-dev pkg-config gcc-mingw-w64-x86-64 curl
  curl -fsSL https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal -q 2>/dev/null
  . "$HOME/.cargo/env"
fi
if command -v rustup >/dev/null 2>&1; then
  rustup target add x86_64-pc-windows-gnu
fi
"""

# Remove build dependencies
REMOVE_BUILD_DEPS_COMMAND = """set -eu
if command -v rustup >/dev/null 2>&1; then
  rm -rf "$HOME/.cargo" "$HOME/.rustup"
fi
apt-get remove -y -qq gcc libc-dev pkg-config gcc-mingw-w64-x86-64 2>/dev/null || true
apt-get autoremove -y -qq 2>/dev/null || true
"""


def expand_powershell(module: PowerShellModule, index: int) -> dict[str, Any]:
    """Expand PowerShell module into dependencies + install steps.
    
    This module sets up the PowerShell wrapper for Wine, enabling PowerShell
    script execution. It supports three modes:
    
    - prebuilt: Download prebuilt binary (default, fastest)
    - build: Build from source (requires Rust toolchain)
    - core: Use PowerShell Core directly (no wrapper, limited compatibility)
    """
    # Merge defaults with user-provided fields
    if module.defaults:
        mode = module.defaults.get("mode", "prebuilt")
        version = module.defaults.get("version", DEFAULT_WRAPPER_VERSION)
    else:
        mode = module.mode or "prebuilt"
        version = module.version or DEFAULT_WRAPPER_VERSION
    
    # Validate mode
    if mode not in ("prebuilt", "build", "core"):
        raise ModuleError(f"modules[{index}].mode must be one of: prebuilt, build, core")
    
    install_steps = []
    dependencies = []
    
    # Common dependencies for all modes
    dependencies.append({
        "kind": "winetricks",
        "verbs": ["powershell_core", "win10"]
    })
    
    if mode == "core":
        # PowerShell Core mode - no wrapper needed
        # Just ensure PowerShell Core is installed via winetricks
        install_steps.append({
            "kind": "script",
            "command": "echo 'PowerShell Core mode - no wrapper setup needed'"
        })
    elif mode == "prebuilt":
        # Prebuilt mode - download binary
        url = PREBUILT_URL_TEMPLATE.format(version=version)
        
        # Try to download prebuilt binary
        download_cmd = DOWNLOAD_WRAPPER_COMMAND.format(url=url)
        install_steps.append({
            "kind": "script",
            "command": download_cmd
        })
        
        # Copy wrapper to system32 location
        install_steps.append({
            "kind": "script",
            "command": COPY_WRAPPER_COMMAND
        })
    
        # Install Chocolatey using PietJankbal's Wine-optimized script
        # This script works around Wine's limitations with the standard Chocolatey installer
        install_steps.append({
            "kind": "script",
            "command": INSTALL_CHOCOLATEY_COMMAND
        })
    
        if mode == "build":
            # Install build dependencies
            install_steps.append({
                "kind": "script",
                "command": INSTALL_BUILD_DEPS_COMMAND
            })
        # Build mode - install deps, build from source, cleanup
        install_steps.append({
            "kind": "script",
            "command": INSTALL_BUILD_DEPS_COMMAND
        })
        
        build_cmd = BUILD_WRAPPER_COMMAND.format(repo_url=POWERSHELL_WRAPPER_REPO)
        install_steps.append({
            "kind": "script",
            "command": build_cmd
        })
        
        install_steps.append({
            "kind": "script",
            "command": COPY_WRAPPER_COMMAND
        })
        
        # Cleanup build artifacts and dependencies
        install_steps.append({
            "kind": "script",
            "command": CLEANUP_BUILD_COMMAND
        })
        
        install_steps.append({
            "kind": "script",
            "command": REMOVE_BUILD_DEPS_COMMAND
        })
    
    return {
        "dependencies": dependencies,
        "install": install_steps,
    }
