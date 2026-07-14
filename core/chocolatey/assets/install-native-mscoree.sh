set -eu
unset WINEDLLOVERRIDES

provider="cfw-native-mscoree-kb958488"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
work="$module_cache/native-mscoree-kb958488"
msu="$work/windows6.1-kb958488-v6001-x64.msu"
msu_url="{{MSCOREE_UPDATE_URL}}"
msu_sha256="{{MSCOREE_UPDATE_SHA256}}"
main_cab_sha256="81d3951c736cccb9578eed19ca9f1d7f68fc17dde1d87eadea72767adbe81734"
x64_sha256="758e5ba89665c574456a2a826ef5a7dc2487c8379893010eb57bc40127ac918f"
x86_sha256="46e9715f3cd09f32fbeaa5379991e9e7daccbd2407c2d061fda3a04f05108133"
x64_component="amd64_netfx-mscoree_dll_31bf3856ad364e35_6.2.7600.16513_none_d9cd6dbd0e6f0bd5"
x86_component="x86_netfx-mscoree_dll_31bf3856ad364e35_6.2.7600.16513_none_7daed23956119a9f"
extract_root="$work/extracted"
log_root="$bundle_root/logs/native-mscoree"
metadata="$bundle_root/metadata/native-mscoree.json"
system32="$wine_prefix/drive_c/windows/system32"
syswow64="$wine_prefix/drive_c/windows/syswow64"
x64_destination="$system32/mscoree.dll"
x86_destination="$syswow64/mscoree.dll"
framework64="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319"
framework32="$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319"

mkdir -p "$work" "$extract_root" "$log_root" "$(dirname "$metadata")" "$system32" "$syswow64"

echo "[cage] Preparing $provider"

verify_file() {
  path="$1"
  expected="$2"
  label="$3"
  if [ ! -s "$path" ]; then
    echo "[cage] ERROR: $label is missing: $path" >&2
    return 1
  fi
  actual="$(sha256sum "$path" | cut -d ' ' -f 1)"
  if [ "$actual" != "$expected" ]; then
    echo "[cage] ERROR: $label checksum mismatch" >&2
    echo "[cage] expected=$expected actual=$actual" >&2
    return 1
  fi
}

write_metadata() {
  python3 - "$metadata" "$provider" "$msu_sha256" "$main_cab_sha256" "$x64_destination" "$x86_destination" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
provider = sys.argv[2]
msu_sha256 = sys.argv[3]
cab_sha256 = sys.argv[4]
x64 = Path(sys.argv[5])
x86 = Path(sys.argv[6])

def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

record = {
    "schemaVersion": "cage.native-mscoree/v1",
    "provider": provider,
    "source": {
        "update": "Windows6.1-KB958488-x64",
        "msuSha256": msu_sha256,
        "cabSha256": cab_sha256,
    },
    "files": {
        "x64": {
            "path": "C:/Windows/System32/mscoree.dll",
            "bytes": x64.stat().st_size,
            "sha256": digest(x64),
        },
        "x86": {
            "path": "C:/Windows/SysWOW64/mscoree.dll",
            "bytes": x86.stat().st_size,
            "sha256": digest(x86),
        },
    },
    "policy": {"mscoree": "native"},
    "logs": {
        "msuExtraction": "logs/native-mscoree/msu-extract.log",
        "cabExtraction": "logs/native-mscoree/cab-extract.log",
        "registry": "logs/native-mscoree/registry.log",
        "inventory": "logs/native-mscoree/inventory.log",
    },
    "status": "passed",
}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY
}

if verify_file "$x64_destination" "$x64_sha256" "native x64 mscoree.dll" && \
   verify_file "$x86_destination" "$x86_sha256" "native x86 mscoree.dll"; then
  echo "[cage] Reusing verified native MSCoree loader"
else
  cage_fetch_verified "$msu_url" "$msu_sha256" "$msu" "$provider"
  rm -rf "$extract_root"
  mkdir -p "$extract_root/msu" "$extract_root/cab"
  7z x -y "$msu" -o"$extract_root/msu" > "$log_root/msu-extract.log"
  main_cab="$extract_root/msu/Windows6.1-KB958488-x64.cab"
  verify_file "$main_cab" "$main_cab_sha256" "KB958488 servicing CAB"
  7z x -y "$main_cab" \
    "$x64_component/mscoree.dll" \
    "$x86_component/mscoree.dll" \
    -o"$extract_root/cab" > "$log_root/cab-extract.log"
  x64_source="$extract_root/cab/$x64_component/mscoree.dll"
  x86_source="$extract_root/cab/$x86_component/mscoree.dll"
  verify_file "$x64_source" "$x64_sha256" "KB958488 x64 mscoree.dll"
  verify_file "$x86_source" "$x86_sha256" "KB958488 x86 mscoree.dll"

  timeout --kill-after=10s 90s wineserver -w >/dev/null 2>&1 || true
  install -m 0644 "$x64_source" "$x64_destination.part"
  mv -f "$x64_destination.part" "$x64_destination"
  install -m 0644 "$x86_source" "$x86_destination.part"
  mv -f "$x86_destination.part" "$x86_destination"
fi

verify_file "$x64_destination" "$x64_sha256" "installed x64 mscoree.dll"
verify_file "$x86_destination" "$x86_sha256" "installed x86 mscoree.dll"
for path in \
  "$framework64/mscoreei.dll" \
  "$framework64/clr.dll" \
  "$framework32/mscoreei.dll" \
  "$framework32/clr.dll"; do
  test -s "$path" || {
    echo "[cage] ERROR: native .NET Framework loader dependency is missing: $path" >&2
    exit 69
  }
done

: > "$log_root/registry.log"
timeout --kill-after=10s 120s wine reg add 'HKCU\Software\Wine\DllOverrides' \
  /v mscoree /d native /f >> "$log_root/registry.log" 2>&1
timeout --kill-after=10s 120s wine reg add 'HKLM\Software\Microsoft\.NETFramework' \
  /v InstallRoot /d 'C:\Windows\Microsoft.NET\Framework64\' /f /reg:64 \
  >> "$log_root/registry.log" 2>&1
timeout --kill-after=10s 120s wine reg add 'HKLM\Software\Microsoft\.NETFramework' \
  /v InstallRoot /d 'C:\Windows\Microsoft.NET\Framework\' /f /reg:32 \
  >> "$log_root/registry.log" 2>&1
timeout --kill-after=10s 120s wine reg add 'HKLM\Software\Microsoft\.NETFramework' \
  /v OnlyUseLatestCLR /t REG_DWORD /d 1 /f /reg:64 \
  >> "$log_root/registry.log" 2>&1
timeout --kill-after=10s 120s wine reg add 'HKLM\Software\Microsoft\.NETFramework' \
  /v OnlyUseLatestCLR /t REG_DWORD /d 1 /f /reg:32 \
  >> "$log_root/registry.log" 2>&1
timeout --kill-after=10s 90s wineserver -w >> "$log_root/registry.log" 2>&1

{
  sha256sum "$x64_destination" "$x86_destination"
  for path in \
    "$framework64/mscoreei.dll" \
    "$framework64/clr.dll" \
    "$framework32/mscoreei.dll" \
    "$framework32/clr.dll"; do
    printf '%s bytes=%s sha256=' "$path" "$(wc -c < "$path")"
    sha256sum "$path" | cut -d ' ' -f 1
  done
} > "$log_root/inventory.log"

write_metadata
echo "[cage] Native MSCoree loader verified from pinned KB958488"
