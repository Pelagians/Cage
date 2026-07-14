#!/usr/bin/env bash
set -euo pipefail

root=/tmp/aik-expand
report="$root/report.txt"
mkdir -p "$root/iso-extract" "$root/winpe" "$root/helper"
: > "$report"
exec > >(tee -a "$report") 2>&1
trap 'rc=$?; echo "diagnostic_exit=$rc"; exit "$rc"' EXIT

url=https://download.microsoft.com/download/8/E/9/8E9BBC64-E6F8-457C-9B8D-F6C9A16E6D6A/KB3AIK_EN.iso

echo '=== partial ISO download ==='
curl -fsSL --retry 3 --connect-timeout 30 --max-time 2400 \
  -H 'Range: bytes=0-1099999999' \
  -D "$root/headers.txt" \
  -o "$root/KB3AIK_EN.partial.iso" "$url"
cat "$root/headers.txt"
stat -c 'partial_iso_bytes=%s' "$root/KB3AIK_EN.partial.iso"
printf 'partial_iso_sha256='; sha256sum "$root/KB3AIK_EN.partial.iso" | cut -d ' ' -f 1

echo '=== extract WinPE.cab ==='
7z x -y "$root/KB3AIK_EN.partial.iso" WinPE.cab -o"$root/iso-extract" >/dev/null
test -s "$root/iso-extract/WinPE.cab"
stat -c 'winpe_cab_bytes=%s' "$root/iso-extract/WinPE.cab"
printf 'winpe_cab_sha256='; sha256sum "$root/iso-extract/WinPE.cab" | cut -d ' ' -f 1

python3 -m pip install --quiet pycdlib
python3 - "$root/KB3AIK_EN.partial.iso" "$root/winpe-range.txt" <<'PY'
import sys
from pathlib import Path
import pycdlib

source = sys.argv[1]
output = Path(sys.argv[2])
iso = pycdlib.PyCdlib()
iso.open(source)
found = None
for dirname, _, filelist in iso.walk(iso_path='/'):
    for name in filelist:
        if name.upper().removesuffix(';1') == 'WINPE.CAB':
            path = (dirname.rstrip('/') + '/' + name).replace('//', '/')
            record = iso.get_record(iso_path=path)
            data_length = record.data_length
            if callable(data_length):
                data_length = data_length()
            extent = record.extent_location()
            found = (path, int(extent), int(data_length))
            break
    if found:
        break
iso.close()
if not found:
    raise SystemExit('WinPE.cab not found in ISO filesystem')
path, extent, size = found
offset = extent * 2048
end = offset + size - 1
output.write_text(f'{offset} {end} {size} {path}\n', encoding='utf-8')
print(f'iso_path={path}')
print(f'iso_extent={extent}')
print(f'winpe_offset={offset}')
print(f'winpe_end={end}')
print(f'winpe_size={size}')
PY

read -r offset end size iso_path < "$root/winpe-range.txt"
echo '=== direct WinPE.cab range ==='
curl -fsSL --retry 3 --connect-timeout 30 --max-time 1200 \
  -H "Range: bytes=$offset-$end" \
  -D "$root/range-headers.txt" \
  -o "$root/WinPE.range.cab" "$url"
cat "$root/range-headers.txt"
stat -c 'range_bytes=%s' "$root/WinPE.range.cab"
test "$(stat -c %s "$root/WinPE.range.cab")" = "$size"
cmp "$root/iso-extract/WinPE.cab" "$root/WinPE.range.cab"
printf 'range_sha256='; sha256sum "$root/WinPE.range.cab" | cut -d ' ' -f 1

echo '=== F3_WINPE.WIM ==='
7z x -y "$root/WinPE.range.cab" F3_WINPE.WIM -o"$root/winpe" >/dev/null
test -s "$root/winpe/F3_WINPE.WIM"
stat -c 'f3_wim_bytes=%s' "$root/winpe/F3_WINPE.WIM"
printf 'f3_wim_sha256='; sha256sum "$root/winpe/F3_WINPE.WIM" | cut -d ' ' -f 1

for item in \
  'amd64_microsoft-windows-deltapackageexpander_31bf3856ad364e35_6.1.7600.16385_none_c5d387d64eb8e1f2/dpx.dll' \
  'amd64_microsoft-windows-cabinet_31bf3856ad364e35_6.1.7600.16385_none_933442c3fb9cbaed/cabinet.dll' \
  'amd64_microsoft-windows-deltacompressionengine_31bf3856ad364e35_6.1.7600.16385_none_9c2159bf9f702069/msdelta.dll' \
  'amd64_microsoft-windows-basic-misc-tools_31bf3856ad364e35_6.1.7600.16385_none_7351a917d91c961e/expand.exe'; do
  7z e -y "$root/winpe/F3_WINPE.WIM" "Windows/winsxs/$item" -o"$root/helper" >/dev/null
done

echo '=== base helper files ==='
for path in "$root/helper"/*; do
  name="$(basename "$path")"
  bytes="$(stat -c %s "$path")"
  digest="$(sha256sum "$path" | cut -d ' ' -f 1)"
  echo "helper=$name bytes=$bytes sha256=$digest"
done
