"""Shared deterministic PowerShell 7 engine installation for Cage modules."""
from __future__ import annotations

from ..build_step import BuildStep

POWERSHELL_VERSION = "7.4.11"
POWERSHELL_ZIP_NAME = f"PowerShell-{POWERSHELL_VERSION}-win-x64.zip"
POWERSHELL_ZIP_URL = (
    "https://github.com/PowerShell/PowerShell/releases/download/"
    f"v{POWERSHELL_VERSION}/{POWERSHELL_ZIP_NAME}"
)
POWERSHELL_ZIP_SHA256 = "558c4115cc6b96cc6a67d74bee40012cf8d38767537f8d2857dc3fa30a63cc63"


def powershell_engine_steps(*, wine_prefix: str = "${WINEPREFIX:-$HOME/.wine}", version_slot: str = "7") -> list[BuildStep]:
    """Return build steps for a real PowerShell 7 engine.

    The engine is downloaded as a pinned/checksummed ZIP and extracted directly
    into the Wine prefix. It intentionally avoids MSI installers and winetricks;
    Wine execution verification happens after module-specific registry prep.
    """
    pwsh_dir = f"{wine_prefix}/drive_c/Program Files/PowerShell/{version_slot}"
    pwsh_exe = f"{pwsh_dir}/pwsh.exe"
    script = f'''set -eu
unset WINEDLLOVERRIDES
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
pwsh_cache="$module_cache/powershell"
pwsh_zip="$pwsh_cache/{POWERSHELL_ZIP_NAME}"
pwsh_zip_url="{POWERSHELL_ZIP_URL}"
pwsh_zip_sha256="{POWERSHELL_ZIP_SHA256}"
pwsh_dir="{pwsh_dir}"
pwsh_exe="{pwsh_exe}"

if [ -f "$pwsh_exe" ]; then
  chmod +x "$pwsh_exe"
  echo "[cage] PowerShell 7 engine already installed: $pwsh_exe"
  exit 0
fi

mkdir -p "$pwsh_cache" "$pwsh_dir"
if [ ! -f "$pwsh_zip" ]; then
  echo "[cage] Downloading PowerShell {POWERSHELL_VERSION} ZIP..."
  curl -fL --retry 3 -o "$pwsh_zip" "$pwsh_zip_url"
fi
actual_pwsh_zip_sha="$(sha256sum "$pwsh_zip" | cut -d ' ' -f 1)"
if [ "$actual_pwsh_zip_sha" != "$pwsh_zip_sha256" ]; then
  echo "[cage] ERROR: PowerShell ZIP checksum mismatch"
  echo "[cage]   expected: $pwsh_zip_sha256"
  echo "[cage]   actual:   $actual_pwsh_zip_sha"
  exit 1
fi

echo "[cage] Extracting PowerShell {POWERSHELL_VERSION} ZIP to $pwsh_dir..."
rm -rf "$pwsh_dir"
mkdir -p "$pwsh_dir"
python3 - "$pwsh_zip" "$pwsh_dir" <<'PY'
import sys
import zipfile
archive, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(archive) as zf:
    zf.extractall(dest)
PY
test -f "$pwsh_exe"
chmod +x "$pwsh_exe"
echo "[cage] PowerShell 7 engine installed: $pwsh_exe"'''
    return [BuildStep(commands=[script], description="Install PowerShell 7 engine")]


__all__ = [
    "POWERSHELL_VERSION",
    "POWERSHELL_ZIP_NAME",
    "POWERSHELL_ZIP_URL",
    "POWERSHELL_ZIP_SHA256",
    "powershell_engine_steps",
]
