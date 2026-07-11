set -eu
unset WINEDLLOVERRIDES
echo "[cage] Bootstrap pinned Chocolatey-for-Wine fork"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
cfw_work="$wine_prefix/.cage/chocolatey-bootstrap/{{BOOTSTRAP_PROFILE_ID}}"
cfw_archive="$cfw_work/Chocolatey-for-wine.7z"
cfw_extract="$cfw_work/extracted/Chocolatey-for-wine"
cfw_payload_cache="$cfw_work/choc_install_files"
cfw_prefix_dir="$wine_prefix/drive_c/ProgramData/Chocolatey-for-wine"
cfw_installer="$cfw_extract/ChoCinstaller_{{CHOCOLATEY_FOR_WINE_INSTALLER_VERSION}}.exe"
canonical_choco="$wine_prefix/drive_c/ProgramData/chocolatey/bin/choco.exe"
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
logs_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-upstream"
metadata="$metadata_dir/chocolatey-upstream-bootstrap.json"

extract_7z_archive() {
  archive="$1"
  destination="$2"
  mkdir -p "$destination"
  for command in 7z 7zz 7za; do
    if command -v "$command" >/dev/null 2>&1; then
      "$command" x -y "$archive" "-o$destination"
      return
    fi
  done
  echo "[cage] ERROR: 7z/7zz/7za is required for Chocolatey-for-Wine extraction" >&2
  exit 69
}

fetch_payload() {
  filename="$1"
  url="$2"
  sha256="$3"
  cage_fetch_verified "$url" "$sha256" "$cfw_payload_cache/$filename" "{{BOOTSTRAP_PROFILE_ID}}"
}

rm -rf "$cfw_work"
mkdir -p "$cfw_payload_cache" "$cfw_prefix_dir" "$metadata_dir" "$logs_dir"
cage_fetch_verified "{{CHOCOLATEY_FOR_WINE_URL}}" "{{CHOCOLATEY_FOR_WINE_SHA256}}" "$cfw_archive" "{{BOOTSTRAP_PROFILE_ID}}"
test "$(sha256sum "$cfw_archive" | cut -d ' ' -f 1)" = "{{CHOCOLATEY_FOR_WINE_SHA256}}"
extract_7z_archive "$cfw_archive" "$cfw_work/extracted"
test -f "$cfw_installer"
test -f "$cfw_extract/choc_install.ps1"
test -f "$cfw_extract/7z.exe"
test -f "$cfw_extract/7z.dll"
test -f "$cfw_extract/c_drive.7z"

fetch_payload "chocolatey.{{CHOCOLATEY_VERSION}}.nupkg" "{{CHOCOLATEY_NUPKG_URL}}" "{{CHOCOLATEY_NUPKG_SHA256}}"
fetch_payload "{{POWERSHELL_MSI_NAME}}" "{{POWERSHELL_MSI_URL}}" "{{POWERSHELL_MSI_SHA256}}"
fetch_payload "ndp48-x86-x64-allos-enu.exe" "{{DOTNET_INSTALLER_URL}}" "{{DOTNET_INSTALLER_SHA256}}"
fetch_payload "windows6.1-kb958488-v6001-x64_a137e4f328f01146dfa75d7b5a576090dee948dc.msu" "{{MSCOREE_UPDATE_URL}}" "{{MSCOREE_UPDATE_SHA256}}"
fetch_payload "d3dcompiler_47.dll" "{{D3DCOMPILER47_URL}}" "{{D3DCOMPILER47_SHA256}}"
fetch_payload "d3dcompiler_47_32.dll" "{{D3DCOMPILER47_X86_URL}}" "{{D3DCOMPILER47_X86_SHA256}}"
fetch_payload "ConEmuPack.230724.7z" "{{CONEMU_URL}}" "{{CONEMU_SHA256}}"
fetch_payload "sevenzipextractor.1.0.19.nupkg" "{{SEVENZIP_EXTRACTOR_URL}}" "{{SEVENZIP_EXTRACTOR_SHA256}}"
fetch_payload "windowsserver2003-kb968930-x64-eng_8ba702aa016e4c5aed581814647f4d55635eff5c.exe" "{{WINDOWS_POWERSHELL_URL}}" "{{WINDOWS_POWERSHELL_SHA256}}"
cage_fetch_verified "{{WINETRICKS_PS1_URL}}" "{{WINETRICKS_PS1_SHA256}}" "$cfw_work/winetricks.ps1" "{{BOOTSTRAP_PROFILE_ID}}"
cp -f "$cfw_work/winetricks.ps1" "$cfw_prefix_dir/winetricks.ps1"

cfw_cache_win="$(winepath -w "$cfw_work")"
cfw_installer_win="$(winepath -w "$cfw_installer")"
export CFW_CACHE="$cfw_cache_win"
export CFW_OFFLINE=1
export CFW_CONTAINER_BUILDER=1
set +e
timeout "${CAGE_CHOCOLATEY_UPSTREAM_TIMEOUT:-3600s}" wine "$cfw_installer_win" /s /q 2>&1 | tee "$logs_dir/installer.log" | grep -a --line-buffered '^\[cfw\] stage='
installer_rc="${PIPESTATUS[0]}"
timeout "${CAGE_CHOCOLATEY_UPSTREAM_SETTLE_TIMEOUT:-300s}" wineserver -w > "$logs_dir/wineserver-settle.log" 2>&1
settle_rc="$?"
path_inventory="$logs_dir/chocolatey-path-inventory.log"
: > "$path_inventory"
record_chocolatey_path() {
  label="$1"
  candidate="$2"
  if [ -f "$candidate" ]; then
    bytes="$(wc -c < "$candidate")"
    echo "[cage] chocolatey-path $label=present bytes=$bytes" | tee -a "$path_inventory"
  else
    echo "[cage] chocolatey-path $label=missing" | tee -a "$path_inventory"
  fi
}
record_chocolatey_path rawRoot "$wine_prefix/drive_c/ProgramData/tools/ChocolateyInstall/choco.exe"
record_chocolatey_path rawRedirect "$wine_prefix/drive_c/ProgramData/tools/ChocolateyInstall/redirects/choco.exe"
record_chocolatey_path canonicalRoot "$wine_prefix/drive_c/ProgramData/chocolatey/choco.exe"
record_chocolatey_path canonicalRedirect "$wine_prefix/drive_c/ProgramData/chocolatey/redirects/choco.exe"
record_chocolatey_path canonicalBin "$canonical_choco"
record_chocolatey_path nestedRoot "$wine_prefix/drive_c/ProgramData/chocolatey/ChocolateyInstall/choco.exe"
record_chocolatey_path nestedRedirect "$wine_prefix/drive_c/ProgramData/chocolatey/ChocolateyInstall/redirects/choco.exe"
python3 - "$wine_prefix/drive_c" "$path_inventory" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
inventory = Path(sys.argv[2])
matches = []
for path in root.rglob('*'):
    try:
        if path.is_file() and path.name.lower() == 'choco.exe':
            matches.append((path.relative_to(root).as_posix(), path.stat().st_size))
    except OSError:
        continue
with inventory.open('a', encoding='utf-8') as output:
    if not matches:
        print('[cage] chocolatey-path discoveredChoco=none', file=output)
    for relative, size in sorted(matches)[:20]:
        print(f'[cage] chocolatey-path discoveredChoco={relative} bytes={size}', file=output)
PY
cat "$path_inventory"
test -f "$canonical_choco"
canonical_rc="$?"

pwsh_direct_log="$logs_dir/pwsh-direct-probe.log"
if [ "$installer_rc" -ne 0 ] || [ "$canonical_rc" -ne 0 ]; then
  pwsh_exe="$wine_prefix/drive_c/Program Files/PowerShell/7/pwsh.exe"
  if [ -f "$pwsh_exe" ]; then
    pwsh_win="$(winepath -w "$pwsh_exe")"
    POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s "${CAGE_CHOCOLATEY_PWSH_PROBE_TIMEOUT:-120s}" wine "$pwsh_win" -NoLogo -NoProfile -NonInteractive -Command "Write-Output '[cfw] stage=direct-pwsh-alive'" > "$pwsh_direct_log" 2>&1
    pwsh_direct_rc="$?"
    tr -d '\r' < "$pwsh_direct_log" | grep -a '^\[cfw\] stage=direct-pwsh-alive$' || true
  else
    pwsh_direct_rc=2
    echo '[cage] direct pwsh probe: executable missing' > "$pwsh_direct_log"
  fi
else
  pwsh_direct_rc=0
  echo '[cage] direct pwsh probe: skipped after successful bootstrap' > "$pwsh_direct_log"
fi
set -e

python3 - "$metadata" "$installer_rc" "$settle_rc" "$canonical_rc" "$pwsh_direct_rc" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
installer_rc, settle_rc, canonical_rc, pwsh_direct_rc = map(int, sys.argv[2:])
passed = installer_rc == 0 and settle_rc == 0 and canonical_rc == 0
record = {
    "schemaVersion": "cage.chocolatey-upstream-bootstrap/v0",
    "status": "passed" if passed else "failed",
    "upstreamInstaller": "ChoCinstaller_{{CHOCOLATEY_FOR_WINE_INSTALLER_VERSION}}.exe",
    "arguments": ["/s", "/q"],
    "offline": True,
    "returnCodes": {"installer": installer_rc, "wineserverSettle": settle_rc, "directPwsh": pwsh_direct_rc},
    "checks": {"canonicalChocoExists": canonical_rc == 0},
    "logs": {
        "installer": "logs/chocolatey-upstream/installer.log",
        "directPwsh": "logs/chocolatey-upstream/pwsh-direct-probe.log",
        "wineserverSettle": "logs/chocolatey-upstream/wineserver-settle.log",
    },
}
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY

if [ "$installer_rc" -ne 0 ] || [ "$settle_rc" -ne 0 ] || [ "$canonical_rc" -ne 0 ]; then
  echo "[cage] ERROR: Chocolatey-for-Wine bootstrap failed (installer=$installer_rc settle=$settle_rc canonical=$canonical_rc)" >&2
  tail -120 "$logs_dir/installer.log" || true
  exit 70
fi
rm -rf "$cfw_work"
echo "[cage] Chocolatey-for-Wine fork created canonical choco.exe"
