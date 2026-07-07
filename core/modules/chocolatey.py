"""Chocolatey package manager module for Wine environments.

This module installs Chocolatey-for-wine (https://github.com/PietJankbal/Chocolatey-for-wine)
which is a custom Chocolatey installer designed for Wine.

PREREQUISITE: This module requires the PowerShell wrapper for wine to be installed first.
The PowerShell wrapper (https://codeberg.org/Synchro/powershell-wrapper-for-wine) provides
a working PowerShell Core environment under Wine that Chocolatey-for-wine depends on.

If the PowerShell wrapper is not detected, this module will automatically install it
before proceeding with Chocolatey-for-wine installation.

The module will:
1. Check if PowerShell wrapper is installed, install if missing
2. Check if Chocolatey is already installed in the Wine prefix
3. If not, download and install Chocolatey-for-wine
4. Install the requested packages
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError


@dataclass
class ChocolateyModule(ModuleBase):
    """Chocolatey package manager module for Wine environments.
    
    This module installs Chocolatey-for-wine (https://github.com/PietJankbal/Chocolatey-for-wine)
    which is a custom Chocolatey installer designed for Wine.
    
    PREREQUISITE: This module requires the PowerShell wrapper for wine to be installed first.
    The PowerShell wrapper (https://codeberg.org/Synchro/powershell-wrapper-for-wine) provides
    a working PowerShell Core environment under Wine that Chocolatey-for-wine depends on.
    
    If the PowerShell wrapper is not detected, this module will automatically install it
    before proceeding with Chocolatey-for-wine installation.
    
    The module will:
    1. Check if PowerShell wrapper is installed, install if missing
    2. Check if Chocolatey is already installed in the Wine prefix
    3. If not, download and install Chocolatey-for-wine
    4. Install the requested packages
    """
    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None  # Optional custom Chocolatey source URL
    version: str = "v0.5c.755"  # Chocolatey-for-wine release version

    def build(self) -> list:
        """Generate build steps for Chocolatey installation and package installation."""
        from ..build_step import BuildStep
        
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
                raise ModuleError(f"chocolatey package names must use letters, numbers, dots, underscores, plus, or dashes only: {pkg}")

        steps = []
        wine_prefix = "${WINEPREFIX:-$HOME/.wine}"
        choco_exe = f"{wine_prefix}/drive_c/ProgramData/chocolatey/bin/choco.exe"
        pwsh_wrapper = f"{wine_prefix}/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
        
        # Step 1: Check and install PowerShell wrapper if missing
        # The PowerShell wrapper for wine is required for Chocolatey-for-wine to work
        steps.append(BuildStep(
            commands=[f'if [ ! -f "{pwsh_wrapper}" ]; then echo "[cage] PowerShell wrapper not found, installing..."; fi'],
            description="Check if PowerShell wrapper is installed",
        ))
        
        # Install PowerShell wrapper for wine if not present
        wrapper_base_url = "https://codeberg.org/Synchro/powershell-wrapper-for-wine/releases/latest/download"
        
        steps.append(BuildStep(
            commands=[f'''if [ ! -f "{pwsh_wrapper}" ]; then
  set -eu
  echo "[cage] Installing PowerShell wrapper for wine..."
  
  # Install PowerShell Core via winetricks first
  winetricks --unattended powershell_core
  
  # Download wrapper executables
  curl -L -o /tmp/powershell64.exe {wrapper_base_url}/powershell64.exe
  curl -L -o /tmp/powershell32.exe {wrapper_base_url}/powershell32.exe
  curl -L -o /tmp/profile.ps1 {wrapper_base_url}/profile.ps1
  
  # Install 64-bit wrapper to system32
  mkdir -p "{wine_prefix}/drive_c/windows/system32/WindowsPowerShell/v1.0"
  cp -f /tmp/powershell64.exe "{wine_prefix}/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
  
  # Install 32-bit wrapper to syswow64
  mkdir -p "{wine_prefix}/drive_c/windows/syswow64/WindowsPowerShell/v1.0"
  cp -f /tmp/powershell32.exe "{wine_prefix}/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"
  
  # Install profile.ps1
  mkdir -p "{wine_prefix}/drive_c/Program Files/PowerShell/7"
  cp -f /tmp/profile.ps1 "{wine_prefix}/drive_c/Program Files/PowerShell/7/profile.ps1"
  
  # Cleanup
  rm -f /tmp/powershell64.exe /tmp/powershell32.exe /tmp/profile.ps1
  
  echo "[cage] PowerShell wrapper installation complete"
fi'''],
            description="Install PowerShell wrapper for wine",
        ))
        
        # Step 2: Check if Chocolatey is already installed, if not install it
        steps.append(BuildStep(
            commands=[f'if [ ! -f "{choco_exe}" ]; then echo "[cage] Chocolatey not found, installing Chocolatey-for-wine..."; fi'],
            description="Check if Chocolatey is installed",
        ))
        
        # Step 3: Install Chocolatey-for-wine if not present
        # Download the 7z release
        release_url = f"https://github.com/PietJankbal/Chocolatey-for-wine/releases/download/{self.version}/Chocolatey-for-wine.7z"
        work_dir = "/tmp/chocolatey-for-wine"
        
        steps.append(BuildStep(
            commands=[f'''if [ ! -f "{choco_exe}" ]; then
  set -eu
  rm -rf {work_dir}
  mkdir -p {work_dir}
  echo "[cage] Downloading Chocolatey-for-wine {self.version}..."
  curl -L -o {work_dir}/Chocolatey-for-wine.7z "{release_url}"
  echo "[cage] Extracting..."
  cd {work_dir}
  7z x -y Chocolatey-for-wine.7z || python3 -c "import py7zr; py7zr.SevenZipFile('Chocolatey-for-wine.7z', mode='r').extractall('.')" 2>/dev/null || (apt-get update -qq && apt-get install -y -qq p7zip-full && 7z x -y Chocolatey-for-wine.7z)
  echo "[cage] Installing Chocolatey-for-wine..."
  # Find the installer exe
  installer=$(find {work_dir} -name "ChoCinstaller_*.exe" -type f | head -1)
  if [ -z "$installer" ]; then
    echo "[cage] ERROR: Could not find Chocolatey installer exe"
    exit 1
  fi
  wine "$installer"
  echo "[cage] Chocolatey-for-wine installation complete"
  rm -rf {work_dir}
fi'''],
            description="Install Chocolatey-for-wine",
        ))
        
        # Step 4: Install packages
        pkg_list = " ".join(packages)
        
        if self.source:
            # Validate source URL
            if not self.source.startswith(("http://", "https://")):
                raise ModuleError(f"Invalid chocolatey source URL: {self.source}")
            steps.append(BuildStep(
                commands=[f'wine "{choco_exe}" install {pkg_list} -y -s {self.source}'],
                description=f"Install Chocolatey packages from custom source: {pkg_list}",
            ))
        else:
            steps.append(BuildStep(
                commands=[f'wine "{choco_exe}" install {pkg_list} -y'],
                description=f"Install Chocolatey packages: {pkg_list}",
            ))

        return steps
