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
    """Return build steps for one pinned, directly verified PowerShell engine.

    Existing installations are reused only when the executable proves the exact
    pinned version. This is important when a compatibility bootstrap has placed
    a different MSI-installed PowerShell in the prefix before Cage applies its
    canonical layer.
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
expected_version="{POWERSHELL_VERSION}"

verify_engine() {{
  [ -f "$pwsh_exe" ] || return 1
  chmod +x "$pwsh_exe"
  engine_log="$(mktemp)"
  normalized_log="$engine_log.normalized"
  set +e
  POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s 120s \
    wine "$pwsh_exe" -NoLogo -NoProfile -NonInteractive -Command \
    'Write-Output ("[cage] engine-version=" + $PSVersionTable.PSVersion.ToString())' \
    >"$engine_log" 2>&1
  engine_rc="$?"
  set -e
  tr -d '\r' < "$engine_log" > "$normalized_log"
  cat "$normalized_log"
  grep -Fqx "[cage] engine-version=$expected_version" "$normalized_log"
  marker_rc="$?"
  rm -f "$engine_log" "$normalized_log"
  [ "$engine_rc" -eq 0 ] && [ "$marker_rc" -eq 0 ]
}}

if verify_engine; then
  echo "[cage] Reusing verified PowerShell $expected_version engine"
  exit 0
fi

mkdir -p "$pwsh_cache"
if [ ! -f "$pwsh_zip" ]; then
  echo "[cage] Downloading PowerShell {POWERSHELL_VERSION} ZIP..."
  curl -fL --retry 3 -o "$pwsh_zip" "$pwsh_zip_url"
fi
actual_pwsh_zip_sha="$(sha256sum "$pwsh_zip" | cut -d ' ' -f 1)"
if [ "$actual_pwsh_zip_sha" != "$pwsh_zip_sha256" ]; then
  echo "[cage] ERROR: PowerShell ZIP checksum mismatch" >&2
  echo "[cage]   expected: $pwsh_zip_sha256" >&2
  echo "[cage]   actual:   $actual_pwsh_zip_sha" >&2
  exit 1
fi

echo "[cage] Installing canonical PowerShell {POWERSHELL_VERSION} engine..."
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
verify_engine || {{
  echo "[cage] ERROR: direct PowerShell engine verification failed" >&2
  exit 70
}}
echo "[cage] PowerShell $expected_version engine verified"'''
    return [BuildStep(commands=[script], description="Install canonical PowerShell 7 engine")]


__all__ = [
    "POWERSHELL_VERSION",
    "POWERSHELL_ZIP_NAME",
    "POWERSHELL_ZIP_URL",
    "POWERSHELL_ZIP_SHA256",
    "powershell_engine_steps",
]
