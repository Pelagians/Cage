set -eu
unset WINEDLLOVERRIDES
echo "[cage] Run upstream Chocolatey-for-wine bootstrap"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
cfw_cache="$module_cache/chocolatey-for-wine/{{CHOCOLATEY_FOR_WINE_VERSION}}"
cfw_extract="$cfw_cache/extracted/Chocolatey-for-wine"
cfw_release_version='{{CHOCOLATEY_FOR_WINE_VERSION}}'
cfw_release_version="${cfw_release_version#v}"
cfw_installer="$cfw_extract/ChoCinstaller_${cfw_release_version}.exe"
cfw_cache_win="$(winepath -w "$cfw_cache")"
cfw_installer_win="$(winepath -w "$cfw_installer")"
canonical_choco="$wine_prefix/drive_c/ProgramData/chocolatey/bin/choco.exe"
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
logs_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-upstream"
metadata="$metadata_dir/chocolatey-upstream-bootstrap.json"
mkdir -p "$metadata_dir" "$logs_dir"
test -f "$cfw_installer"

# The release installer is the upstream compatibility mechanism. Its exit code
# is evidence only; canonical choco.exe and the later readiness proof are Cage's
# success boundary.
export CFW_CACHE="$cfw_cache_win"
set +e
timeout "${CAGE_CHOCOLATEY_UPSTREAM_TIMEOUT:-3600s}" wine "$cfw_installer_win" /s /q > "$logs_dir/installer.log" 2>&1
installer_rc="$?"
timeout "${CAGE_CHOCOLATEY_UPSTREAM_SETTLE_TIMEOUT:-300s}" wineserver -w > "$logs_dir/wineserver-settle.log" 2>&1
settle_rc="$?"
test -f "$canonical_choco"
canonical_rc="$?"
set -e

python3 - "$metadata" "$installer_rc" "$settle_rc" "$canonical_rc" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
installer_rc, settle_rc, canonical_rc = map(int, sys.argv[2:])
record = {
    "schemaVersion": "cage.chocolatey-upstream-bootstrap/v0",
    "status": "passed" if canonical_rc == 0 else "failed",
    "upstreamInstaller": "ChoCinstaller_{{CHOCOLATEY_FOR_WINE_VERSION}}.exe",
    "arguments": ["/s", "/q"],
    "returnCodes": {"installer": installer_rc, "wineserverSettle": settle_rc},
    "checks": {"canonicalChocoExists": canonical_rc == 0},
    "logs": {
        "installer": "logs/chocolatey-upstream/installer.log",
        "wineserverSettle": "logs/chocolatey-upstream/wineserver-settle.log",
    },
}
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY

if [ "$canonical_rc" -ne 0 ]; then
  echo "[cage] ERROR: upstream bootstrap did not create canonical choco.exe" >&2
  tail -120 "$logs_dir/installer.log" || true
  exit 70
fi
echo "[cage] Upstream Chocolatey-for-wine bootstrap created canonical choco.exe"
