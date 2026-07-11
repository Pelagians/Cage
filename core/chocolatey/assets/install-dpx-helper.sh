set -eu
unset WINEDLLOVERRIDES

wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
work="$module_cache/cfw-dpx-helper"
archive="$work/powershell2.7z"
archive_url="https://github.com/PietJankbal/powershell-wrapper-for-wine/releases/download/0.5a/powershell2.7z"
archive_sha512="1dbd829b097706a24866aa4e4c0a7de876d91f189567d7d8dfc3448319d2e97438e1d013ab61b57d77653598784258ccef8cff646081f2c6937985910fdee9c1"
extract_root="$work/extracted"
system32="$wine_prefix/drive_c/windows/system32"
expand_dir="$system32/expnd"
expand_exe="$expand_dir/expand.exe"
dpx_dll="$system32/dpx.dll"
log_root="$bundle_root/logs/powershell-engine"
metadata="$bundle_root/metadata/cfw-dpx-helper.json"

mkdir -p "$work" "$extract_root" "$expand_dir" "$log_root" "$(dirname "$metadata")"

if [ -s "$expand_exe" ] && [ -s "$dpx_dll" ]; then
  echo "[cage] Reusing CFW native DPX extraction helper"
else
  if [ ! -f "$archive" ]; then
    curl -fL --retry 3 --connect-timeout 30 --max-time 1200 \
      -o "$archive.part" "$archive_url"
    mv -f "$archive.part" "$archive"
  fi
  actual_sha512="$(sha512sum "$archive" | cut -d ' ' -f 1)"
  if [ "$actual_sha512" != "$archive_sha512" ]; then
    echo "[cage] ERROR: CFW DPX helper archive checksum mismatch" >&2
    echo "[cage] expected=$archive_sha512 actual=$actual_sha512" >&2
    exit 1
  fi

  rm -rf "$extract_root"
  mkdir -p "$extract_root"
  7z e -y "$archive" \
    '-ir!dpx.dll' '-ir!expand.exe' '-ir!msdelta.dll' \
    -o"$extract_root" >"$log_root/dpx-helper-extract.log"
  test -s "$extract_root/dpx.dll"
  test -s "$extract_root/expand.exe"
  test -s "$extract_root/msdelta.dll"

  install -m 0644 "$extract_root/dpx.dll" "$dpx_dll.part"
  mv -f "$dpx_dll.part" "$dpx_dll"
  install -m 0755 "$extract_root/expand.exe" "$expand_exe.part"
  mv -f "$expand_exe.part" "$expand_exe"
fi

python3 - "$metadata" "$archive_sha512" "$dpx_dll" "$expand_exe" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
archive_sha512 = sys.argv[2]
dpx = Path(sys.argv[3])
expand = Path(sys.argv[4])

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

record = {
    "schemaVersion": "cage.cfw-dpx-helper/v1",
    "source": {
        "url": "https://github.com/PietJankbal/powershell-wrapper-for-wine/releases/download/0.5a/powershell2.7z",
        "sha512": archive_sha512,
    },
    "files": {
        "dpx.dll": {"path": "C:/Windows/System32/dpx.dll", "sha256": sha256(dpx)},
        "expand.exe": {"path": "C:/Windows/System32/expnd/expand.exe", "sha256": sha256(expand)},
    },
    "status": "passed",
}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY

test -s "$expand_exe"
test -s "$dpx_dll"
echo "[cage] CFW native DPX extraction helper verified"
