"""PowerShell wrapper module for Wine environments.

The wrapper is a separate PowerShell capability provider. It shares Cage's
pinned PowerShell 7 engine step, then installs Synchro's checked wrapper assets
for the WindowsPowerShell.exe shim surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase
from .powershell_engine import powershell_engine_steps
from ..powershell_wrapper_assets import (
    POWERSHELL_WRAPPER_BASE_URL,
    POWERSHELL_WRAPPER_SHA256,
    POWERSHELL_WRAPPER_VERSION,
)
from ..build_step import BuildStep

DEFAULT_WRAPPER_VERSION = POWERSHELL_WRAPPER_VERSION
DEFAULT_WRAPPER_SHA256 = POWERSHELL_WRAPPER_SHA256


@dataclass
class PowerShellWrapperModule(ModuleBase):
    """Install powershell-wrapper-for-wine from pinned release assets."""

    type: str = "powershell-wrapper"
    version: str = "7"
    wrapper_version: str = DEFAULT_WRAPPER_VERSION

    def capabilities(self) -> dict[str, str]:
        """Return PowerShell-related capability slots claimed by the wrapper."""
        return {
            "engine": "powershell-zip",
            "winps-shim": "powershell-wrapper",
            "shim-library": "powershell-wrapper-for-wine",
        }

    def build(self) -> list[BuildStep]:
        """Generate build steps for the PowerShell wrapper installation."""
        wine_prefix = "${WINEPREFIX:-$HOME/.wine}"
        wrapper_base_url = (
            POWERSHELL_WRAPPER_BASE_URL
            if self.wrapper_version == DEFAULT_WRAPPER_VERSION
            else (
                "https://codeberg.org/Synchro/powershell-wrapper-for-wine/releases/download/"
                f"{self.wrapper_version}"
            )
        )
        hashes = DEFAULT_WRAPPER_SHA256 if self.wrapper_version == DEFAULT_WRAPPER_VERSION else {
            "powershell64.exe": "",
            "powershell32.exe": "",
            "profile.ps1": "",
        }

        script = f'''set -eu
unset WINEDLLOVERRIDES
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
wrapper_cache="$module_cache/powershell-wrapper/{self.wrapper_version}"
wrapper_base_url="{wrapper_base_url}"
wrapper64_cache="$wrapper_cache/powershell64.exe"
wrapper32_cache="$wrapper_cache/powershell32.exe"
profile_cache="$wrapper_cache/profile.ps1"
wrapper64_sha256="{hashes['powershell64.exe']}"
wrapper32_sha256="{hashes['powershell32.exe']}"
profile_sha256="{hashes['profile.ps1']}"
wrapper64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
wrapper32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"
profile="$wine_prefix/drive_c/Program Files/PowerShell/{self.version}/profile.ps1"

if [ -f "$wrapper64" ] && [ -f "$wrapper32" ] && [ -f "$profile" ]; then
  echo "[cage] PowerShell wrapper already installed"
  exit 0
fi

mkdir -p "$wrapper_cache"
if [ ! -f "$wrapper64_cache" ]; then
  curl -fL --retry 3 -o "$wrapper64_cache" "$wrapper_base_url/powershell64.exe"
fi
if [ ! -f "$wrapper32_cache" ]; then
  curl -fL --retry 3 -o "$wrapper32_cache" "$wrapper_base_url/powershell32.exe"
fi
if [ ! -f "$profile_cache" ]; then
  curl -fL --retry 3 -o "$profile_cache" "$wrapper_base_url/profile.ps1"
fi

actual_wrapper64_sha="$(sha256sum "$wrapper64_cache" | cut -d ' ' -f 1)"
actual_wrapper32_sha="$(sha256sum "$wrapper32_cache" | cut -d ' ' -f 1)"
actual_profile_sha="$(sha256sum "$profile_cache" | cut -d ' ' -f 1)"
if [ -n "$wrapper64_sha256" ] && [ "$actual_wrapper64_sha" != "$wrapper64_sha256" ]; then
  echo "[cage] ERROR: powershell64.exe checksum mismatch"
  exit 1
fi
if [ -n "$wrapper32_sha256" ] && [ "$actual_wrapper32_sha" != "$wrapper32_sha256" ]; then
  echo "[cage] ERROR: powershell32.exe checksum mismatch"
  exit 1
fi
if [ -n "$profile_sha256" ] && [ "$actual_profile_sha" != "$profile_sha256" ]; then
  echo "[cage] ERROR: profile.ps1 checksum mismatch"
  exit 1
fi

mkdir -p "$(dirname "$wrapper64")" "$(dirname "$wrapper32")" "$(dirname "$profile")"
cp -f "$wrapper64_cache" "$wrapper64"
cp -f "$wrapper32_cache" "$wrapper32"
cp -f "$profile_cache" "$profile"

echo "[cage] Verifying PowerShell wrapper..."
timeout 120s wine "$wrapper64" -NoLogo -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'
echo "[cage] PowerShell wrapper installation complete"'''

        return [
            *powershell_engine_steps(wine_prefix=wine_prefix, version_slot=self.version),
            BuildStep(
                commands=[script],
                description=f"Install PowerShell wrapper ({self.wrapper_version})",
            ),
        ]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.version != "7":
            result["version"] = self.version
        if self.wrapper_version != DEFAULT_WRAPPER_VERSION:
            result["wrapperVersion"] = self.wrapper_version
        return result


__all__ = ["PowerShellWrapperModule", "DEFAULT_WRAPPER_VERSION", "DEFAULT_WRAPPER_SHA256"]
