set -eu
unset WINEDLLOVERRIDES
echo "[cage] Install Chocolatey PowerShell wrapper {{POWERSHELL_WRAPPER_VERSION}}"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
cache_root="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bootstrap_dir="$cache_root/bootstrap/{{BOOTSTRAP_PROFILE_ID}}/powershell-wrapper/{{POWERSHELL_WRAPPER_VERSION}}"
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
metadata="$metadata_dir/chocolatey-powershell-wrapper.json"
wrapper64="$bootstrap_dir/powershell64.exe"
wrapper32="$bootstrap_dir/powershell32.exe"
profile="$bootstrap_dir/profile.ps1"
wrapper64_destination="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
wrapper32_destination="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"
profile_destination="$wine_prefix/drive_c/Program Files/PowerShell/7/profile.ps1"
mkdir -p "$bootstrap_dir" "$metadata_dir"
cage_fetch_verified "{{POWERSHELL_WRAPPER_BASE_URL}}/powershell64.exe" "{{POWERSHELL_WRAPPER64_SHA256}}" "$wrapper64" "{{BOOTSTRAP_PROFILE_ID}}"
cage_fetch_verified "{{POWERSHELL_WRAPPER_BASE_URL}}/powershell32.exe" "{{POWERSHELL_WRAPPER32_SHA256}}" "$wrapper32" "{{BOOTSTRAP_PROFILE_ID}}"
cage_fetch_verified "{{POWERSHELL_WRAPPER_BASE_URL}}/profile.ps1" "{{POWERSHELL_WRAPPER_PROFILE_SHA256}}" "$profile" "{{BOOTSTRAP_PROFILE_ID}}"

promote() {
  source=$1
  destination=$2
  mkdir -p "$(dirname "$destination")"
  temporary="$destination.part"
  cp "$source" "$temporary"
  mv "$temporary" "$destination"
}

promote "$wrapper64" "$wrapper64_destination"
promote "$wrapper32" "$wrapper32_destination"
promote "$profile" "$profile_destination"
printf '%s\n' 'CAGE-POWERSHELL-WRAPPER-64' > "$metadata_dir/wrapper64-sentinel.txt.part"
mv "$metadata_dir/wrapper64-sentinel.txt.part" "$metadata_dir/wrapper64-sentinel.txt"
printf '%s\n' 'CAGE-POWERSHELL-WRAPPER-32' > "$metadata_dir/wrapper32-sentinel.txt.part"
mv "$metadata_dir/wrapper32-sentinel.txt.part" "$metadata_dir/wrapper32-sentinel.txt"
python3 - "$metadata" "$wrapper64_destination" "$wrapper32_destination" "$profile_destination" <<'PY'
import json
import sys
from pathlib import Path

metadata, wrapper64, wrapper32, profile = map(Path, sys.argv[1:])
record = {
    "schemaVersion": "cage.chocolatey-powershell-wrapper/v0",
    "status": "installed",
    "files": [
        {"architecture": "x64", "destination": "C:/windows/system32/WindowsPowerShell/v1.0/powershell.exe", "sha256": "{{POWERSHELL_WRAPPER64_SHA256}}"},
        {"architecture": "x86", "destination": "C:/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe", "sha256": "{{POWERSHELL_WRAPPER32_SHA256}}"},
        {"destination": "C:/Program Files/PowerShell/7/profile.ps1", "sha256": "{{POWERSHELL_WRAPPER_PROFILE_SHA256}}"},
    ],
    "sentinels": ["wrapper64-sentinel.txt", "wrapper32-sentinel.txt"],
}
temporary = metadata.with_suffix(metadata.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(metadata)
PY
echo "[cage] Chocolatey PowerShell wrapper installed"
