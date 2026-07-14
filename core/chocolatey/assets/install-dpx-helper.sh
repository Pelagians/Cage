set -eu
unset WINEDLLOVERRIDES

provider="cfw-dpx-helper-aik-winpe"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
work="$module_cache/cfw-dpx-helper-aik-winpe"
source_cache="$work/source"
extract_root="$work/extracted"
iso_url="https://download.microsoft.com/download/8/E/9/8E9BBC64-E6F8-457C-9B8D-F6C9A16E6D6A/KB3AIK_EN.iso"
iso_total_size="1789542400"
range_start="640526336"
range_end="1086964920"
range_size="446438585"
winpe_cab="$source_cache/WinPE.cab"
winpe_cab_sha256="b8db22bef35f091b6b63d223118c55f833856be0d535465ce5a06a51ff38fa27"
f3_wim="$extract_root/F3_WINPE.WIM"
f3_wim_sha256="fdfd889f5131898d9a3e68e39c24d8d6ad1f53765522f0280899e54620be47ff"
system32="$wine_prefix/drive_c/windows/system32"
expand_dir="$system32/expnd"
expand_exe="$expand_dir/expand.exe"
cabinet_dll="$expand_dir/cabinet.dll"
dpx_dll="$expand_dir/dpx.dll"
msdelta_dll="$expand_dir/msdelta.dll"
expand_sha256="72cedaef15d65f2a88a19f1fff3e420a978b93b0e5bb9fd160fb26b7b9aca8cc"
cabinet_sha256="5d66d94a347bc43d0d8157cc5a24abaf2f60b5dbeb2b1527c251452128e00ee2"
dpx_sha256="3e77ebc2f91887d69d53ec4cf83d84572d0d1c234ea7eed06e0e3020baa29794"
msdelta_sha256="9b57d563ad6535adf6a83da33b3391bb80ac3266f5663077cff0cee43700ef47"
log_root="$bundle_root/logs/powershell-engine"
metadata="$bundle_root/metadata/cfw-dpx-helper.json"
range_headers="$log_root/aik-winpe-range.headers"

mkdir -p "$work" "$source_cache" "$extract_root" "$expand_dir" "$log_root" "$(dirname "$metadata")"

echo "[cage] Preparing $provider"

verify_sha256() {
  path="$1"
  expected="$2"
  label="$3"
  [ -s "$path" ] || return 1
  actual="$(sha256sum "$path" | cut -d ' ' -f 1)"
  if [ "$actual" != "$expected" ]; then
    echo "[cage] ERROR: $label checksum mismatch" >&2
    echo "[cage] expected=$expected actual=$actual" >&2
    return 1
  fi
}

verify_installed() {
  verify_sha256 "$expand_exe" "$expand_sha256" expand.exe &&
  verify_sha256 "$cabinet_dll" "$cabinet_sha256" cabinet.dll &&
  verify_sha256 "$dpx_dll" "$dpx_sha256" dpx.dll &&
  verify_sha256 "$msdelta_dll" "$msdelta_sha256" msdelta.dll
}

if verify_installed; then
  echo "[cage] Reusing verified native AIK DPX extraction helper"
else
  exec 9>"$work/source.lock"
  flock 9
  if ! verify_sha256 "$winpe_cab" "$winpe_cab_sha256" WinPE.cab; then
    rm -f "$winpe_cab" "$winpe_cab.part" "$range_headers"
    curl -fsSL --retry 3 --connect-timeout 30 --max-time 1800 \
      -H "Range: bytes=$range_start-$range_end" \
      -D "$range_headers" \
      -o "$winpe_cab.part" "$iso_url"
    actual_size="$(stat -c %s "$winpe_cab.part")"
    if [ "$actual_size" != "$range_size" ]; then
      echo "[cage] ERROR: AIK WinPE.cab range size mismatch" >&2
      echo "[cage] expected=$range_size actual=$actual_size" >&2
      exit 1
    fi
    normalized_headers="$range_headers.normalized"
    tr -d '\r' < "$range_headers" > "$normalized_headers"
    expected_range="Content-Range: bytes $range_start-$range_end/$iso_total_size"
    if ! grep -Fqi "$expected_range" "$normalized_headers"; then
      echo "[cage] ERROR: AIK server did not return the expected byte range" >&2
      cat "$normalized_headers" >&2
      exit 1
    fi
    verify_sha256 "$winpe_cab.part" "$winpe_cab_sha256" WinPE.cab
    mv -f "$winpe_cab.part" "$winpe_cab"
  fi
  flock -u 9

  rm -rf "$extract_root"
  mkdir -p "$extract_root/helper"
  7z x -y "$winpe_cab" F3_WINPE.WIM -o"$extract_root" >"$log_root/aik-winpe-cab-extract.log"
  verify_sha256 "$f3_wim" "$f3_wim_sha256" F3_WINPE.WIM

  for item in \
    'amd64_microsoft-windows-deltapackageexpander_31bf3856ad364e35_6.1.7600.16385_none_c5d387d64eb8e1f2/dpx.dll' \
    'amd64_microsoft-windows-cabinet_31bf3856ad364e35_6.1.7600.16385_none_933442c3fb9cbaed/cabinet.dll' \
    'amd64_microsoft-windows-deltacompressionengine_31bf3856ad364e35_6.1.7600.16385_none_9c2159bf9f702069/msdelta.dll' \
    'amd64_microsoft-windows-basic-misc-tools_31bf3856ad364e35_6.1.7600.16385_none_7351a917d91c961e/expand.exe'; do
    7z e -y "$f3_wim" "Windows/winsxs/$item" -o"$extract_root/helper" \
      >>"$log_root/aik-winpe-helper-extract.log"
  done

  verify_sha256 "$extract_root/helper/expand.exe" "$expand_sha256" expand.exe
  verify_sha256 "$extract_root/helper/cabinet.dll" "$cabinet_sha256" cabinet.dll
  verify_sha256 "$extract_root/helper/dpx.dll" "$dpx_sha256" dpx.dll
  verify_sha256 "$extract_root/helper/msdelta.dll" "$msdelta_sha256" msdelta.dll

  install -m 0755 "$extract_root/helper/expand.exe" "$expand_exe.part"
  mv -f "$expand_exe.part" "$expand_exe"
  for name in cabinet.dll dpx.dll msdelta.dll; do
    install -m 0644 "$extract_root/helper/$name" "$expand_dir/$name.part"
    mv -f "$expand_dir/$name.part" "$expand_dir/$name"
  done
fi

policy_key='HKCU\Software\Wine\AppDefaults\expand.exe\DllOverrides'
timeout --kill-after=10s 120s wine reg add "$policy_key" /v cabinet /d native,builtin /f \
  >"$log_root/aik-expand-policy.log" 2>&1
timeout --kill-after=10s 120s wine reg add "$policy_key" /v msdelta /d native,builtin /f \
  >>"$log_root/aik-expand-policy.log" 2>&1
timeout --kill-after=10s 90s wineserver -w >>"$log_root/aik-expand-policy.log" 2>&1

verify_installed
python3 - "$metadata" "$provider" "$iso_url" "$range_start" "$range_end" "$range_size" \
  "$winpe_cab_sha256" "$f3_wim_sha256" "$expand_exe" "$cabinet_dll" "$dpx_dll" "$msdelta_dll" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
provider = sys.argv[2]
iso_url = sys.argv[3]
range_start = int(sys.argv[4])
range_end = int(sys.argv[5])
range_size = int(sys.argv[6])
winpe_sha256 = sys.argv[7]
f3_sha256 = sys.argv[8]
files = {
    "expand.exe": Path(sys.argv[9]),
    "cabinet.dll": Path(sys.argv[10]),
    "dpx.dll": Path(sys.argv[11]),
    "msdelta.dll": Path(sys.argv[12]),
}

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
        "kind": "http-range",
        "url": iso_url,
        "range": {"start": range_start, "end": range_end, "size": range_size},
        "winPECabSha256": winpe_sha256,
        "f3WinPEWimSha256": f3_sha256,
    },
    "files": {
        name: {
            "path": "C:/Windows/System32/expnd/" + name,
            "sha256": sha256(path),
        }
        for name, path in files.items()
    },
    "winePolicy": {
        "application": "expand.exe",
        "dllOverrides": {
            "cabinet": "native,builtin",
            "msdelta": "native,builtin",
        },
    },
    "logs": {
        "rangeHeaders": "logs/powershell-engine/aik-winpe-range.headers",
        "cabExtraction": "logs/powershell-engine/aik-winpe-cab-extract.log",
        "helperExtraction": "logs/powershell-engine/aik-winpe-helper-extract.log",
        "winePolicy": "logs/powershell-engine/aik-expand-policy.log",
    },
    "status": "passed",
}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY

echo "[cage] CFW native DPX extraction helper verified from the official AIK WinPE payload"
