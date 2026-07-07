"""PowerShell module type for Cage.

Installs PowerShell Core in Wine using the powershell-wrapper-for-wine project.
This provides a working PowerShell environment under Wine by:
1. Installing PowerShell Core via winetricks
2. Replacing the PowerShell executables with Wine-compatible wrappers
3. Installing the wrapper's profile.ps1

Reference: https://codeberg.org/Synchro/powershell-wrapper-for-wine
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase


@dataclass
class PowerShellModule(ModuleBase):
    """PowerShell Core module for Wine environments.
    
    Uses the powershell-wrapper-for-wine project to install a working
    PowerShell Core environment under Wine.
    """
    type: str = "powershell"
    version: str = "7"  # PowerShell major version (7 for Core)
    
    def build(self) -> list:
        """Generate build steps for PowerShell installation."""
        from ..build_step import BuildStep
        
        steps = []
        
        # Step 1: Install PowerShell Core via winetricks
        steps.append(BuildStep(
            command="winetricks --unattended powershell_core",
            label="Install PowerShell Core via winetricks",
        ))
        
        # Step 2: Download wrapper executables from Codeberg release
        # The wrapper provides powershell32.exe, powershell64.exe, and profile.ps1
        wrapper_base_url = "https://codeberg.org/Synchro/powershell-wrapper-for-wine/releases/latest/download"
        
        steps.append(BuildStep(
            command=f"curl -L -o /tmp/powershell64.exe {wrapper_base_url}/powershell64.exe",
            label="Download PowerShell 64-bit wrapper",
        ))
        
        steps.append(BuildStep(
            command=f"curl -L -o /tmp/powershell32.exe {wrapper_base_url}/powershell32.exe",
            label="Download PowerShell 32-bit wrapper",
        ))
        
        steps.append(BuildStep(
            command=f"curl -L -o /tmp/profile.ps1 {wrapper_base_url}/profile.ps1",
            label="Download PowerShell profile",
        ))
        
        # Step 3: Install wrapper executables into Wine prefix
        wine_prefix = "${WINEPREFIX:-$HOME/.wine}"
        
        # Install 64-bit wrapper to system32
        steps.append(BuildStep(
            command=f'mkdir -p "{wine_prefix}/drive_c/windows/system32/WindowsPowerShell/v1.0"',
            label="Create PowerShell 64-bit directory",
        ))
        
        steps.append(BuildStep(
            command=f'cp -f /tmp/powershell64.exe "{wine_prefix}/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"',
            label="Install PowerShell 64-bit wrapper",
        ))
        
        # Install 32-bit wrapper to syswow64
        steps.append(BuildStep(
            command=f'mkdir -p "{wine_prefix}/drive_c/windows/syswow64/WindowsPowerShell/v1.0"',
            label="Create PowerShell 32-bit directory",
        ))
        
        steps.append(BuildStep(
            command=f'cp -f /tmp/powershell32.exe "{wine_prefix}/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"',
            label="Install PowerShell 32-bit wrapper",
        ))
        
        # Install profile.ps1
        steps.append(BuildStep(
            command=f'mkdir -p "{wine_prefix}/drive_c/Program Files/PowerShell/{self.version}"',
            label="Create PowerShell profile directory",
        ))
        
        steps.append(BuildStep(
            command=f'cp -f /tmp/profile.ps1 "{wine_prefix}/drive_c/Program Files/PowerShell/{self.version}/profile.ps1"',
            label="Install PowerShell profile",
        ))
        
        # Cleanup
        steps.append(BuildStep(
            command="rm -f /tmp/powershell64.exe /tmp/powershell32.exe /tmp/profile.ps1",
            label="Cleanup temporary files",
        ))
        
        return steps
    
    def to_dict(self) -> dict[str, Any]:
        """Convert module back to dict for serialization."""
        result = {"type": self.type}
        if self.version != "7":
            result["version"] = self.version
        return result
