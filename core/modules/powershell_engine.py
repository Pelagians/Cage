"""Experimental standalone PowerShell engine provider."""
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
    """Return the legacy PowerShell Core experiment with strict verification.

    Current Cage Wine runners do not pass this proof, so Chocolatey does not use
    this provider. It remains available only for focused runtime experiments.
    """
    pwsh_dir = f"{wine_prefix}/drive_c/Program Files/PowerShell/{version_slot}"
    pwsh_exe = f"{pwsh_dir}/pwsh.exe"
    script = f"""set -eu
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
  timeout --kill-after=10s 120s winecfg /v win10 >>"$policy_log" 2>&1
  timeout --kill-after=10s 120s wineserver -w >>"$policy_log" 2>&1 || true
  for override in 'amsi=' 'dwmapi=' 'rpcrt4=native,builtin'; do
    name="${{override%%=*}}"
    value="${{override#*=}}"
    timeout --kill-after=10s 120s wine reg add "$policy_key" /v "$name" /d "$value" /f >>"$policy_log" 2>&1
  done
  timeout --kill-after=10s 120s wineserver -w >>"$policy_log" 2>&1 || true
}}

verify_engine() {{
  [ -f "$pwsh_exe" ] || return 1
  chmod +x "$pwsh_exe"
  cat > "$probe_script.part" <<'PS1'
param([Parameter(Mandatory = $true)][string]$MarkerPath)
$ErrorActionPreference = 'Stop'
$version = $PSVersionTable.PSVersion.ToString()
[System.IO.File]::WriteAllText($MarkerPath, $version)
[Console]::Out.WriteLine('[cage] engine-version=' + $version)
PS1
  mv -f "$probe_script.part" "$probe_script"
  rm -f "$probe_marker"
  probe_script_win="$(winepath -w "$probe_script")"
  probe_marker_win="$(winepath -w "$probe_marker")"
  engine_log="$engine_logs/direct-probe.log"
  normalized_log="$engine_logs/direct-probe.normalized.log"
  set +e
  POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s 180s wine "$pwsh_exe" \
    -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File "$probe_script_win" "$probe_marker_win" >"$engine_log" 2>&1
  engine_rc="$?"
  timeout --kill-after=10s 60s wineserver -w >>"$engine_log" 2>&1
  settle_rc="$?"
  tr -d '\r' < "$engine_log" > "$normalized_log"
  grep -Fqx "[cage] engine-version=$expected_version" "$normalized_log"
  stdout_rc="$?"
  if [ -f "$probe_marker" ] && [ "$(tr -d '\r\n' < "$probe_marker")" = "$expected_version" ]; then sentinel_rc=0; else sentinel_rc=1; fi
  set -e
  cat "$normalized_log"
  [ "$engine_rc" -eq 0 ] && [ "$settle_rc" -eq 0 ] && [ "$stdout_rc" -eq 0 ] && [ "$sentinel_rc" -eq 0 ]
}}

prepare_pwsh_policy
if verify_engine; then exit 0; fi
mkdir -p "$pwsh_cache"
if [ ! -f "$pwsh_zip" ]; then curl -fL --retry 3 -o "$pwsh_zip" "$pwsh_zip_url"; fi
actual="$(sha256sum "$pwsh_zip" | cut -d ' ' -f 1)"
[ "$actual" = "$pwsh_zip_sha256" ] || exit 1
rm -rf "$pwsh_dir"
mkdir -p "$pwsh_dir"
python3 - "$pwsh_zip" "$pwsh_dir" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PY
chmod +x "$pwsh_exe"
prepare_pwsh_policy
verify_engine || exit 70"""
    return [BuildStep(
        commands=[script],
        description="Probe experimental PowerShell 7 engine",
        kind="wine-run",
        timeout=1200,
        metadata={
            "engine": f"powershell-zip-{POWERSHELL_VERSION}",
            "experimental": True,
        },
    )]


__all__ = [
    "POWERSHELL_VERSION",
    "POWERSHELL_ZIP_NAME",
    "POWERSHELL_ZIP_URL",
    "POWERSHELL_ZIP_SHA256",
    "powershell_engine_steps",
]
