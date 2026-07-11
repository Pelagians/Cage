set -eu
unset WINEDLLOVERRIDES
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
wrapper64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
wrapper32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"
backend64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/ps51.exe"
backend32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/ps51.exe"
profile64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/profile.ps1"
profile32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/profile.ps1"
profile_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
fragment_dir="$profile_root/profile.d"
probe_ps1="$profile_root/layer-probe.ps1"
probe_json="$profile_root/layer-probe.json"
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
metadata="$metadata_dir/powershell-layer.json"

for required in \
  "$backend64" "$backend32" "$wrapper64" "$wrapper32" \
  "$profile64" "$profile32" \
  "$fragment_dir/10-synchro.ps1" \
  "$fragment_dir/20-chocolatey.ps1" \
  "$fragment_dir/30-cfw-winetricks.ps1" \
  "$fragment_dir/40-cfw-command-adapters.ps1"; do
  test -s "$required"
done

cat > "$probe_ps1.part" <<'PS'
$ErrorActionPreference = 'Stop'
$actualVersion = $PSVersionTable.PSVersion.ToString()
if (-not $actualVersion.StartsWith('5.1')) {
    throw "Unexpected PowerShell version: $actualVersion"
}
if (-not (Get-Alias -Name winetricks -ErrorAction SilentlyContinue)) {
    throw 'CFW winetricks alias was not loaded'
}
if (-not (Get-Command -Name Update-SessionEnvironment -ErrorAction SilentlyContinue)) {
    throw 'Chocolatey profile helpers were not loaded'
}
$processPath = (Get-Process -Id $PID).Path
$record = [ordered]@{
    schemaVersion = 'cage.powershell-layer/v1'
    status = 'passed'
    engine = $actualVersion
    edition = 'Desktop'
    processPath = $processPath
    winetricksAlias = $true
    chocolateyProfile = $true
}
$record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath 'C:\ProgramData\Cage\PowerShell\layer-probe.json' -Encoding UTF8
Write-Output '[cage] composed-powershell-layer-ok'
PS
mv -f "$probe_ps1.part" "$probe_ps1"
probe_ps1_win="$(winepath -w "$probe_ps1")"
export PWSH_PATH='C:\windows\system32\WindowsPowerShell\v1.0\ps51.exe'
export PSHACKS=1
export PS_FROM=' measure -s '
export PS_TO=' measure -sum '

x64_log="$(mktemp)"
x86_log="$(mktemp)"
x64_normalized="$x64_log.normalized"
x86_normalized="$x86_log.normalized"
set +e
timeout --kill-after=10s 240s wine "$wrapper64" -NoLogo -NonInteractive -File "$probe_ps1_win" >"$x64_log" 2>&1
x64_rc="$?"
timeout --kill-after=10s 240s wine "$wrapper32" -NoLogo -NonInteractive -Command \
  'Write-Output "[cage] synchro-x86-composed-ok"' >"$x86_log" 2>&1
x86_rc="$?"
timeout --kill-after=10s 240s wine "$wrapper64" -NoLogo -NonInteractive -Command 'exit 37' >/dev/null 2>&1
exit_rc="$?"
timeout --kill-after=10s 90s wineserver -w >/dev/null 2>&1
settle_rc="$?"
tr -d '\r' < "$x64_log" > "$x64_normalized"
tr -d '\r' < "$x86_log" > "$x86_normalized"
grep -Fqx '[cage] composed-powershell-layer-ok' "$x64_normalized"
x64_marker_rc="$?"
grep -Fqx '[cage] synchro-x86-composed-ok' "$x86_normalized"
x86_marker_rc="$?"
set -e
cat "$x64_normalized"
cat "$x86_normalized"
test -s "$probe_json"

if [ "$x64_rc" -ne 0 ] || [ "$x86_rc" -ne 0 ] || [ "$exit_rc" -ne 37 ] || \
   [ "$settle_rc" -ne 0 ] || [ "$x64_marker_rc" -ne 0 ] || [ "$x86_marker_rc" -ne 0 ]; then
  echo "[cage] ERROR: composed PowerShell layer failed" >&2
  exit 70
fi

mkdir -p "$metadata_dir"
python3 - "$probe_json" "$metadata" <<'PY'
import json
import sys
from pathlib import Path
source = Path(sys.argv[1])
destination = Path(sys.argv[2])
record = json.loads(source.read_text(encoding="utf-8-sig"))
temporary = destination.with_suffix(destination.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(destination)
PY

echo "[cage] Composed Synchro and CFW Windows PowerShell layer verified"
