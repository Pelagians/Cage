"""Canonical Windows PowerShell compatibility layer for Wine.

Cage owns the real PowerShell engine and the stable profile loader. Synchro's
powershell-wrapper-for-wine owns the Windows PowerShell executable surface and
its upstream compatibility profile, which Cage loads as an ordered fragment.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from .powershell_engine import POWERSHELL_VERSION, powershell_engine_steps
from ..powershell_wrapper_assets import (
    POWERSHELL_WRAPPER_BASE_URL,
    POWERSHELL_WRAPPER_SHA256,
    POWERSHELL_WRAPPER_VERSION,
)
from ..build_step import BuildStep

DEFAULT_WRAPPER_VERSION = POWERSHELL_WRAPPER_VERSION
DEFAULT_WRAPPER_SHA256 = POWERSHELL_WRAPPER_SHA256

_PROFILE_LOADER = r"""$ErrorActionPreference = 'Stop'
$fragmentRoot = Join-Path $env:ProgramData 'Cage\PowerShell\profile.d'
if (Test-Path -LiteralPath $fragmentRoot -PathType Container) {
    Get-ChildItem -LiteralPath $fragmentRoot -Filter '*.ps1' -File |
        Sort-Object -Property Name |
        ForEach-Object { . $_.FullName }
}
Remove-Variable fragmentRoot -ErrorAction SilentlyContinue
"""


def _encoded(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def powershell_wrapper_steps(
    *,
    wine_prefix: str = "${WINEPREFIX:-$HOME/.wine}",
    version_slot: str = "7",
    wrapper_version: str = DEFAULT_WRAPPER_VERSION,
    include_engine: bool = True,
) -> list[BuildStep]:
    """Install and prove the pinned Synchro compatibility provider."""
    if wrapper_version != DEFAULT_WRAPPER_VERSION:
        raise ModuleError(
            "powershell-wrapper currently accepts only the pinned, checksummed "
            f"release {DEFAULT_WRAPPER_VERSION}; requested {wrapper_version}"
        )

    upstream_fragment = (
        "$synchroProfile = Join-Path $env:ProgramData "
        f"'Cage\\PowerShell\\upstream\\synchro-{wrapper_version}\\profile.ps1'\n"
        "if (-not (Test-Path -LiteralPath $synchroProfile -PathType Leaf)) {\n"
        "    throw \"Synchro PowerShell compatibility profile is missing: $synchroProfile\"\n"
        "}\n"
        ". $synchroProfile\n"
        "Remove-Variable synchroProfile -ErrorAction SilentlyContinue\n"
    )
    wine_prefix_value = wine_prefix
    script = f'''set -eu
unset WINEDLLOVERRIDES
wine_prefix="{wine_prefix_value}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
wrapper_cache="$module_cache/powershell-wrapper/{wrapper_version}"
wrapper_base_url="{POWERSHELL_WRAPPER_BASE_URL}"
wrapper64_cache="$wrapper_cache/powershell64.exe"
wrapper32_cache="$wrapper_cache/powershell32.exe"
profile_cache="$wrapper_cache/profile.ps1"
wrapper64_sha256="{DEFAULT_WRAPPER_SHA256['powershell64.exe']}"
wrapper32_sha256="{DEFAULT_WRAPPER_SHA256['powershell32.exe']}"
profile_sha256="{DEFAULT_WRAPPER_SHA256['profile.ps1']}"
wrapper64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
wrapper32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"
pwsh_exe="$wine_prefix/drive_c/Program Files/PowerShell/{version_slot}/pwsh.exe"
profile_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
fragment_dir="$profile_root/profile.d"
upstream_dir="$profile_root/upstream/synchro-{wrapper_version}"
upstream_profile="$upstream_dir/profile.ps1"
profile="$wine_prefix/drive_c/Program Files/PowerShell/{version_slot}/profile.ps1"
profile_loader_b64="{_encoded(_PROFILE_LOADER)}"
synchro_fragment_b64="{_encoded(upstream_fragment)}"

mkdir -p "$wrapper_cache"
fetch_wrapper_asset() {{
  destination="$1"
  filename="$2"
  if [ ! -f "$destination" ]; then
    curl -fL --retry 3 -o "$destination" "$wrapper_base_url/$filename"
  fi
}}
fetch_wrapper_asset "$wrapper64_cache" powershell64.exe
fetch_wrapper_asset "$wrapper32_cache" powershell32.exe
fetch_wrapper_asset "$profile_cache" profile.ps1

verify_hash() {{
  path="$1"
  expected="$2"
  label="$3"
  actual="$(sha256sum "$path" | cut -d ' ' -f 1)"
  if [ "$actual" != "$expected" ]; then
    echo "[cage] ERROR: $label checksum mismatch" >&2
    echo "[cage]   expected: $expected" >&2
    echo "[cage]   actual:   $actual" >&2
    exit 1
  fi
}}
verify_hash "$wrapper64_cache" "$wrapper64_sha256" powershell64.exe
verify_hash "$wrapper32_cache" "$wrapper32_sha256" powershell32.exe
verify_hash "$profile_cache" "$profile_sha256" profile.ps1

test -f "$pwsh_exe"
mkdir -p "$(dirname "$wrapper64")" "$(dirname "$wrapper32")" \
  "$(dirname "$profile")" "$fragment_dir" "$upstream_dir"
cp -f "$wrapper64_cache" "$wrapper64"
cp -f "$wrapper32_cache" "$wrapper32"
cp -f "$profile_cache" "$upstream_profile"
printf '%s' "$profile_loader_b64" | base64 -d > "$profile.part"
mv -f "$profile.part" "$profile"
printf '%s' "$synchro_fragment_b64" | base64 -d > "$fragment_dir/10-synchro.ps1.part"
mv -f "$fragment_dir/10-synchro.ps1.part" "$fragment_dir/10-synchro.ps1"

for required in "$wrapper64" "$wrapper32" "$profile" "$upstream_profile" "$fragment_dir/10-synchro.ps1"; do
  test -s "$required"
done

echo "[cage] Verifying Synchro PowerShell compatibility layer..."
x64_log="$(mktemp)"
x86_log="$(mktemp)"
set +e
POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s 120s \
  wine "$wrapper64" -NoLogo -NonInteractive -Command \
  'Write-Output "[cage] synchro-x64-ok"' >"$x64_log" 2>&1
x64_rc="$?"
POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s 120s \
  wine "$wrapper32" -NoLogo -NonInteractive -Command \
  'Write-Output "[cage] synchro-x86-ok"' >"$x86_log" 2>&1
x86_rc="$?"
POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s 120s \
  wine "$wrapper64" -NoLogo -NonInteractive -Command 'exit 37' >/dev/null 2>&1
exit_rc="$?"
set -e
tr -d '\r' < "$x64_log"
tr -d '\r' < "$x86_log"
grep -Fqx '[cage] synchro-x64-ok' "$x64_log"
grep -Fqx '[cage] synchro-x86-ok' "$x86_log"
rm -f "$x64_log" "$x86_log"
if [ "$x64_rc" -ne 0 ] || [ "$x86_rc" -ne 0 ] || [ "$exit_rc" -ne 37 ]; then
  echo "[cage] ERROR: Synchro wrapper verification failed (x64=$x64_rc x86=$x86_rc exit=$exit_rc)" >&2
  exit 70
fi
echo "[cage] Synchro {wrapper_version} layer verified on PowerShell {POWERSHELL_VERSION}"'''

    steps: list[BuildStep] = []
    if include_engine:
        steps.extend(powershell_engine_steps(wine_prefix=wine_prefix, version_slot=version_slot))
    steps.append(BuildStep(
        commands=[script],
        description=f"Install canonical Synchro PowerShell layer ({wrapper_version})",
    ))
    return steps


@dataclass
class PowerShellWrapperModule(ModuleBase):
    """Install powershell-wrapper-for-wine from pinned release assets."""

    type: str = "powershell-wrapper"
    version: str = "7"
    wrapper_version: str = DEFAULT_WRAPPER_VERSION

    def capabilities(self) -> dict[str, str]:
        return {
            "engine": f"powershell-zip-{POWERSHELL_VERSION}",
            "winps-shim": f"synchro-{DEFAULT_WRAPPER_VERSION}",
        }

    def build(self) -> list[BuildStep]:
        return powershell_wrapper_steps(
            version_slot=self.version,
            wrapper_version=self.wrapper_version,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.version != "7":
            result["version"] = self.version
        if self.wrapper_version != DEFAULT_WRAPPER_VERSION:
            result["wrapperVersion"] = self.wrapper_version
        return result


__all__ = [
    "PowerShellWrapperModule",
    "DEFAULT_WRAPPER_VERSION",
    "DEFAULT_WRAPPER_SHA256",
    "powershell_wrapper_steps",
]
