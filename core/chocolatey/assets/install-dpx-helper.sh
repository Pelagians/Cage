set -eu
unset WINEDLLOVERRIDES

provider="cfw-dpx-helper-from-c-drive"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
work="$module_cache/cfw-dpx-helper"
extract_root="$work/extracted"
system32="$wine_prefix/drive_c/windows/system32"
expand_dir="$system32/expnd"
expand_exe="$expand_dir/expand.exe"
dpx_dll="$system32/dpx.dll"
msdelta_dll="$system32/msdelta.dll"
expand_msdelta="$expand_dir/msdelta.dll"
log_root="$bundle_root/logs/powershell-engine"
metadata="$bundle_root/metadata/cfw-dpx-helper.json"
archive_inventory="$log_root/cfw-c-drive-inventory.log"

mkdir -p "$work" "$extract_root" "$expand_dir" "$log_root" "$(dirname "$metadata")"

echo "[cage] Preparing $provider"
source_archive=""
source_sha256=""
source_relative=""

if [ -s "$expand_exe" ] && [ -s "$dpx_dll" ] && [ -s "$msdelta_dll" ]; then
  echo "[cage] Reusing CFW native DPX extraction helper"
else
  source_archive="$(find "$module_cache/cfw-bootstrap" -type f -name 'c_drive.7z' -print -quit 2>/dev/null || true)"
  if [ -z "$source_archive" ] || [ ! -s "$source_archive" ]; then
    echo "[cage] ERROR: retained CFW c_drive.7z is unavailable" >&2
    exit 67
  fi

  source_sha256="$(sha256sum "$source_archive" | cut -d ' ' -f 1)"
  source_relative="${source_archive#"$module_cache"/}"
  7z l "$source_archive" > "$archive_inventory"

  rm -rf "$extract_root"
  mkdir -p "$extract_root"
  set +e
  7z e -y "$source_archive" \
    '-ir!dpx.dll' '-ir!expand.exe' '-ir!msdelta.dll' \
    -o"$extract_root" >"$log_root/dpx-helper-extract.log" 2>&1
  extract_rc="$?"
  set -e

  if [ "$extract_rc" -ne 0 ] || \
     [ ! -s "$extract_root/dpx.dll" ] || \
     [ ! -s "$extract_root/expand.exe" ] || \
     [ ! -s "$extract_root/msdelta.dll" ]; then
    echo "[cage] ERROR: CFW c_drive.7z does not contain the complete DPX helper set" >&2
    grep -Eai '(^|[/\\])(dpx\.dll|expand\.exe|msdelta\.dll)$' "$archive_inventory" || true
    exit 68
  fi

  install -m 0644 "$extract_root/dpx.dll" "$dpx_dll.part"
  mv -f "$dpx_dll.part" "$dpx_dll"
  install -m 0644 "$extract_root/msdelta.dll" "$msdelta_dll.part"
  mv -f "$msdelta_dll.part" "$msdelta_dll"
  install -m 0644 "$extract_root/msdelta.dll" "$expand_msdelta.part"
  mv -f "$expand_msdelta.part" "$expand_msdelta"
  install -m 0755 "$extract_root/expand.exe" "$expand_exe.part"
  mv -f "$expand_exe.part" "$expand_exe"
fi

python3 - "$metadata" "$provider" "$source_relative" "$source_sha256" "$dpx_dll" "$msdelta_dll" "$expand_exe" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
provider = sys.argv[2]
source_relative = sys.argv[3]
source_sha256 = sys.argv[4]
dpx = Path(sys.argv[5])
msdelta = Path(sys.argv[6])
expand = Path(sys.argv[7])

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

record = {
    "schemaVersion": "cage.cfw-dpx-helper/v1",
    "provider": provider,
    "source": {
        "kind": "retained-cfw-component",
        "path": source_relative,
        "sha256": source_sha256,
    },
    "files": {
        "dpx.dll": {"path": "C:/Windows/System32/dpx.dll", "sha256": sha256(dpx)},
        "msdelta.dll": {"path": "C:/Windows/System32/msdelta.dll", "sha256": sha256(msdelta)},
        "expand.exe": {"path": "C:/Windows/System32/expnd/expand.exe", "sha256": sha256(expand)},
    },
    "logs": {"archiveInventory": "logs/powershell-engine/cfw-c-drive-inventory.log"},
    "status": "passed",
}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY

test -s "$expand_exe"
test -s "$dpx_dll"
test -s "$msdelta_dll"
echo "[cage] CFW native DPX extraction helper verified from retained c_drive.7z"
