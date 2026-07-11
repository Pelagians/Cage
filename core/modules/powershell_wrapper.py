"""Synchro Windows PowerShell compatibility providers for Wine."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError
from .powershell_engine import (
    POWERSHELL_VERSION,
    WINDOWS_POWERSHELL_PROVIDER,
    powershell_engine_steps,
)
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
    Get-ChildItem -LiteralPath $fragmentRoot -Filter '*.ps1' |
        Sort-Object -Property Name |
        ForEach-Object { . $_.FullName }
}
Remove-Variable fragmentRoot -ErrorAction SilentlyContinue
"""

_PS51_SYNCHRO_FRAGMENT = r"""# Synchro wrapper policy compatible with Windows PowerShell 5.1.
[System.Environment]::SetEnvironmentVariable('PWSH_PATH', 'C:\Windows\System32\WindowsPowerShell\v1.0\ps51.exe', 'User')
[System.Environment]::SetEnvironmentVariable('PSHACKS', '1', 'User')
[System.Environment]::SetEnvironmentVariable('PS_FROM', ' measure -s ', 'User')
[System.Environment]::SetEnvironmentVariable('PS_TO', ' measure -sum ', 'User')
"""


def _encoded(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _validate_version(wrapper_version: str) -> None:
    if wrapper_version != DEFAULT_WRAPPER_VERSION:
        raise ModuleError(
            "powershell-wrapper currently accepts only the pinned, checksummed "
            f"release {DEFAULT_WRAPPER_VERSION}; requested {wrapper_version}"
        )


def windows_powershell_wrapper_steps(
    *,
    wine_prefix: str = "${WINEPREFIX:-$HOME/.wine}",
    wrapper_version: str = DEFAULT_WRAPPER_VERSION,
) -> list[BuildStep]:
    """Install Synchro over Cage's verified Windows PowerShell 5.1 backend."""
    _validate_version(wrapper_version)
    script = f'''set -eu
unset WINEDLLOVERRIDES
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
bundle_root="${{CAGE_BUNDLE_MOUNT:-/opt/cage}}"
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
backend64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/ps51.exe"
backend32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/ps51.exe"
profile64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/profile.ps1"
profile32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/profile.ps1"
profile_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
fragment_dir="$profile_root/profile.d"
upstream_dir="$profile_root/upstream/synchro-{wrapper_version}"
upstream_profile="$upstream_dir/profile.ps1"
profile_loader_b64="{_encoded(_PROFILE_LOADER)}"
synchro_fragment_b64="{_encoded(_PS51_SYNCHRO_FRAGMENT)}"
metadata="$bundle_root/metadata/powershell-wrapper.json"
log_root="$bundle_root/logs/powershell-wrapper"

mkdir -p "$wrapper_cache" "$fragment_dir" "$upstream_dir" "$log_root" "$(dirname "$metadata")"
fetch_asset() {{
  destination="$1"
  filename="$2"
  if [ ! -f "$destination" ]; then
    curl -fL --retry 3 --connect-timeout 30 --max-time 600 -o "$destination.part" "$wrapper_base_url/$filename"
    mv -f "$destination.part" "$destination"
  fi
}}
fetch_asset "$wrapper64_cache" powershell64.exe
fetch_asset "$wrapper32_cache" powershell32.exe
fetch_asset "$profile_cache" profile.ps1
verify_hash() {{
  path="$1" expected="$2" label="$3"
  actual="$(sha256sum "$path" | cut -d ' ' -f 1)"
  if [ "$actual" != "$expected" ]; then
    echo "[cage] ERROR: $label checksum mismatch" >&2
    exit 1
  fi
}}
verify_hash "$wrapper64_cache" "$wrapper64_sha256" powershell64.exe
verify_hash "$wrapper32_cache" "$wrapper32_sha256" powershell32.exe
verify_hash "$profile_cache" "$profile_sha256" profile.ps1

test -s "$backend64"
test -s "$backend32"
mkdir -p "$(dirname "$wrapper64")" "$(dirname "$wrapper32")"
cp -f "$wrapper64_cache" "$wrapper64"
cp -f "$wrapper32_cache" "$wrapper32"
cp -f "$profile_cache" "$upstream_profile"
for profile in "$profile64" "$profile32"; do
  printf '%s' "$profile_loader_b64" | base64 -d > "$profile.part"
  mv -f "$profile.part" "$profile"
done
printf '%s' "$synchro_fragment_b64" | base64 -d > "$fragment_dir/10-synchro.ps1.part"
mv -f "$fragment_dir/10-synchro.ps1.part" "$fragment_dir/10-synchro.ps1"

export PWSH_PATH='C:\\windows\\system32\\WindowsPowerShell\\v1.0\\ps51.exe'
export PSHACKS=1
export PS_FROM=' measure -s '
export PS_TO=' measure -sum '
for pair in \
  'PWSH_PATH=C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\ps51.exe' \
  'PSHACKS=1' \
  'PS_FROM= measure -s ' \
  'PS_TO= measure -sum '; do
  name="${{pair%%=*}}"
  value="${{pair#*=}}"
  timeout --kill-after=10s 120s wine reg add 'HKCU\\Environment' /v "$name" /d "$value" /f >/dev/null
 done

x64_log="$log_root/x64.log"
x86_log="$log_root/x86.log"
x64_normalized="$log_root/x64.normalized.log"
x86_normalized="$log_root/x86.normalized.log"
set +e
timeout --kill-after=10s 240s wine "$wrapper64" -NoLogo -NonInteractive -Command \
  'Write-Output "[cage] synchro-x64-ok"' >"$x64_log" 2>&1
x64_rc="$?"
timeout --kill-after=10s 240s wine "$wrapper32" -NoLogo -NonInteractive -Command \
  'Write-Output "[cage] synchro-x86-ok"' >"$x86_log" 2>&1
x86_rc="$?"
timeout --kill-after=10s 240s wine "$wrapper64" -NoLogo -NonInteractive -Command 'exit 37' >/dev/null 2>&1
exit_rc="$?"
timeout --kill-after=10s 90s wineserver -w >/dev/null 2>&1
settle_rc="$?"
tr -d '\r' < "$x64_log" > "$x64_normalized"
tr -d '\r' < "$x86_log" > "$x86_normalized"
grep -Fqx '[cage] synchro-x64-ok' "$x64_normalized"
x64_marker_rc="$?"
grep -Fqx '[cage] synchro-x86-ok' "$x86_normalized"
x86_marker_rc="$?"
set -e
cat "$x64_normalized"
cat "$x86_normalized"

python3 - "$metadata" "$x64_rc" "$x86_rc" "$exit_rc" "$settle_rc" "$x64_marker_rc" "$x86_marker_rc" <<'PY'
import json
import sys
from pathlib import Path
output = Path(sys.argv[1])
values = [int(value) for value in sys.argv[2:]]
record = {{
    "schemaVersion": "cage.powershell-wrapper/v1",
    "provider": "synchro-{wrapper_version}",
    "backend": "{WINDOWS_POWERSHELL_PROVIDER}",
    "upstreamProfileStored": True,
    "upstreamProfileLoaded": False,
    "returnCodes": {{
        "x64": values[0], "x86": values[1], "exit37": values[2],
        "wineserverSettle": values[3], "x64Marker": values[4], "x86Marker": values[5],
    }},
    "status": "passed" if values == [0, 0, 37, 0, 0, 0] else "failed",
}}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY
if [ "$x64_rc" -ne 0 ] || [ "$x86_rc" -ne 0 ] || [ "$exit_rc" -ne 37 ] || \
   [ "$settle_rc" -ne 0 ] || [ "$x64_marker_rc" -ne 0 ] || [ "$x86_marker_rc" -ne 0 ]; then
  echo "[cage] ERROR: Synchro PS5.1 verification failed" >&2
  exit 70
fi
echo "[cage] Synchro {wrapper_version} verified over Windows PowerShell 5.1"'''
    return [BuildStep(
        commands=[script],
        description=f"Install Synchro PowerShell layer ({wrapper_version})",
        kind="wine-run",
        timeout=1200,
        metadata={
            "winpsShim": f"synchro-{wrapper_version}",
            "engine": WINDOWS_POWERSHELL_PROVIDER,
            "evidence": "metadata/powershell-wrapper.json",
        },
    )]


def powershell_wrapper_steps(
    *,
    wine_prefix: str = "${WINEPREFIX:-$HOME/.wine}",
    version_slot: str = "7",
    wrapper_version: str = DEFAULT_WRAPPER_VERSION,
    include_engine: bool = True,
) -> list[BuildStep]:
    """Legacy PowerShell Core experiment retained for standalone diagnosis."""
    _validate_version(wrapper_version)
    steps: list[BuildStep] = []
    if include_engine:
        steps.extend(powershell_engine_steps(wine_prefix=wine_prefix, version_slot=version_slot))
    # A verified Core backend is required before this experimental path can be
    # promoted. Chocolatey uses windows_powershell_wrapper_steps instead.
    return steps


@dataclass
class PowerShellWrapperModule(ModuleBase):
    """Experimental standalone PowerShell Core module."""

    type: str = "powershell-wrapper"
    version: str = "7"
    wrapper_version: str = DEFAULT_WRAPPER_VERSION

    def capabilities(self) -> dict[str, str]:
        return {
            "engine": f"powershell-zip-{POWERSHELL_VERSION}",
            "winps-shim": f"synchro-{DEFAULT_WRAPPER_VERSION}-experimental",
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
    "windows_powershell_wrapper_steps",
]
