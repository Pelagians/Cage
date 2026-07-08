"""PowerShell wrapper module for Wine environments.

This module installs the Synchro powershell-wrapper-for-wine project as a
standalone capability. It is intentionally separate from Chocolatey-for-wine;
for now recipes cannot combine this module with the chocolatey module because
both replace the same PowerShell surface with different compatibility layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase


DEFAULT_WRAPPER_VERSION = "v4.2.0"


@dataclass
class PowerShellWrapperModule(ModuleBase):
    """Install powershell-wrapper-for-wine from pinned release assets."""

    type: str = "powershell-wrapper"
    version: str = "7"
    wrapper_version: str = DEFAULT_WRAPPER_VERSION

    def build(self) -> list:
        """Generate build steps for the PowerShell wrapper installation."""
        from ..build_step import BuildStep

        wine_prefix = "${WINEPREFIX:-$HOME/.wine}"
        wrapper_base_url = (
            "https://codeberg.org/Synchro/powershell-wrapper-for-wine/releases/download/"
            f"{self.wrapper_version}"
        )

        commands = [
            f'''set -eu
export WINEDLLOVERRIDES=""
wine_prefix="{wine_prefix}"
wrapper64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
wrapper32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"
profile="$wine_prefix/drive_c/Program Files/PowerShell/{self.version}/profile.ps1"

if [ -f "$wrapper64" ] && [ -f "$profile" ]; then
  echo "[cage] PowerShell wrapper already installed"
  exit 0
fi

echo "[cage] Installing PowerShell Core via winetricks..."
winetricks --unattended powershell_core

work_dir="/tmp/cage-powershell-wrapper"
rm -rf "$work_dir"
mkdir -p "$work_dir"

echo "[cage] Downloading powershell-wrapper-for-wine {self.wrapper_version}..."
curl -fL --retry 3 -o "$work_dir/powershell64.exe" "{wrapper_base_url}/powershell64.exe"
curl -fL --retry 3 -o "$work_dir/powershell32.exe" "{wrapper_base_url}/powershell32.exe"
curl -fL --retry 3 -o "$work_dir/profile.ps1" "{wrapper_base_url}/profile.ps1"
test -s "$work_dir/powershell64.exe"
test -s "$work_dir/powershell32.exe"
test -s "$work_dir/profile.ps1"

mkdir -p "$(dirname "$wrapper64")" "$(dirname "$wrapper32")" "$(dirname "$profile")"
cp -f "$work_dir/powershell64.exe" "$wrapper64"
cp -f "$work_dir/powershell32.exe" "$wrapper32"
cp -f "$work_dir/profile.ps1" "$profile"

rm -rf "$work_dir"

echo "[cage] Verifying PowerShell wrapper..."
timeout 120s wine "$wrapper64" -NoLogo -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'
echo "[cage] PowerShell wrapper installation complete"'''
        ]

        return [
            BuildStep(
                commands=commands,
                description=f"Install PowerShell wrapper ({self.wrapper_version})",
            )
        ]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.version != "7":
            result["version"] = self.version
        if self.wrapper_version != DEFAULT_WRAPPER_VERSION:
            result["wrapperVersion"] = self.wrapper_version
        return result
