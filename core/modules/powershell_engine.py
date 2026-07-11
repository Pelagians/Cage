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
    pinned version. The provider also owns the Wine policy required by pwsh.exe:
    Windows 10 mode plus the per-application DLL overrides already established by
    Cage's standalone PowerShell runtime proof.
    """
    pwsh_dir = f"{wine_prefix}/drive_c/Program Files/PowerShell/{version_slot}"
    pwsh_exe = f"{pwsh_dir}/pwsh.exe"
    script = f'''set -eu
unset WINEDLLOVERRIDES
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
bundle_root="${{CAGE_BUNDLE_MOUNT:-/opt/cage}}"
engine_logs="$bundle_root/logs/powershell-engine"
engine_metadata="$bundle_root/metadata/powershell-engine.json"
pwsh_cache="$module_cache/powershell"
pwsh_zip="$pwsh_cache/{POWERSHELL_ZIP_NAME}"
pwsh_zip_url="{POWERSHELL_ZIP_URL}"
pwsh_zip_sha256="{POWERSHELL_ZIP_SHA256}"
pwsh_dir="{pwsh_dir}"
pwsh_exe="{pwsh_exe}"
expected_version="{POWERSHELL_VERSION}"
policy_key='HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides'
probe_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
probe_script="$probe_root/engine-probe.ps1"
probe_marker="$probe_root/engine-probe-ok.txt"

mkdir -p "$pwsh_cache" "$engine_logs" "$probe_root" "$(dirname "$engine_metadata")"

prepare_pwsh_policy() {{
  policy_log="$engine_logs/wine-policy.log"
  : > "$policy_log"
  echo "[cage] Configuring Wine policy for pwsh.exe" | tee -a "$policy_log"
  timeout --kill-after=10s 120s winecfg /v win10 >>"$policy_log" 2>&1
  timeout --kill-after=10s 120s wineserver -w >>"$policy_log" 2>&1 || true
  for override in 'amsi=' 'dwmapi=' 'rpcrt4=native,builtin'; do
    name="${{override%%=*}}"
    value="${{override#*=}}"
    timeout --kill-after=10s 120s wine reg add "$policy_key" /v "$name" /d "$value" /f \
      >>"$policy_log" 2>&1
  done
  timeout --kill-after=10s 120s wineserver -w >>"$policy_log" 2>&1 || true
}}

write_probe_script() {{
  cat > "$probe_script.part" <<'PS1'
param([Parameter(Mandatory = $true)][string]$MarkerPath)
$ErrorActionPreference = 'Stop'
$version = $PSVersionTable.PSVersion.ToString()
[System.IO.File]::WriteAllText($MarkerPath, $version)
[Console]::Out.WriteLine('[cage] engine-version=' + $version)
PS1
  mv -f "$probe_script.part" "$probe_script"
}}

verify_engine() {{
  [ -f "$pwsh_exe" ] || return 1
  chmod +x "$pwsh_exe"
  write_probe_script
  rm -f "$probe_marker"
  probe_script_win="$(winepath -w "$probe_script")"
  probe_marker_win="$(winepath -w "$probe_marker")"
  engine_log="$engine_logs/direct-probe.log"
  normalized_log="$engine_logs/direct-probe.normalized.log"

  set +e
  POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s 180s \
    wine "$pwsh_exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
      -File "$probe_script_win" "$probe_marker_win" \
    >"$engine_log" 2>&1
  engine_rc="$?"
  timeout --kill-after=10s 60s wineserver -w >>"$engine_log" 2>&1
  settle_rc="$?"
  tr -d '\r' < "$engine_log" > "$normalized_log"
  grep -Fqx "[cage] engine-version=$expected_version" "$normalized_log"
  stdout_rc="$?"
  if [ -f "$probe_marker" ] && [ "$(tr -d '\r\n' < "$probe_marker")" = "$expected_version" ]; then
    sentinel_rc=0
  else
    sentinel_rc=1
  fi
  set -e

  cat "$normalized_log"
  python3 - "$engine_metadata" "$expected_version" "$engine_rc" "$settle_rc" "$stdout_rc" "$sentinel_rc" <<'PY'
import json
import sys
from pathlib import Path
output = Path(sys.argv[1])
record = {{
    "schemaVersion": "cage.powershell-engine/v1",
    "expectedVersion": sys.argv[2],
    "returnCodes": {{
        "process": int(sys.argv[3]),
        "wineserverSettle": int(sys.argv[4]),
        "stdoutMarker": int(sys.argv[5]),
        "fileSentinel": int(sys.argv[6]),
    }},
    "status": "passed" if all(int(value) == 0 for value in sys.argv[3:]) else "failed",
    "logs": {{"directProbe": "logs/powershell-engine/direct-probe.log"}},
}}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY
  [ "$engine_rc" -eq 0 ] && [ "$settle_rc" -eq 0 ] && [ "$stdout_rc" -eq 0 ] && [ "$sentinel_rc" -eq 0 ]
}}

prepare_pwsh_policy
if verify_engine; then
  echo "[cage] Reusing verified PowerShell $expected_version engine"
  exit 0
fi

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
prepare_pwsh_policy
verify_engine || {{
  echo "[cage] ERROR: direct PowerShell engine verification failed" >&2
  exit 70
}}
echo "[cage] PowerShell $expected_version engine verified"'''
    return [BuildStep(
        commands=[script],
        description="Install canonical PowerShell 7 engine",
        kind="wine-run",
        timeout=1200,
        metadata={
            "engine": f"powershell-zip-{POWERSHELL_VERSION}",
            "evidence": "metadata/powershell-engine.json",
        },
    )]


__all__ = [
    "POWERSHELL_VERSION",
    "POWERSHELL_ZIP_NAME",
    "POWERSHELL_ZIP_URL",
    "POWERSHELL_ZIP_SHA256",
    "powershell_engine_steps",
]
