#!/usr/bin/env bash
set -euo pipefail

root=/tmp/aik-expand
report="$root/report.txt"
mkdir -p "$root/winpe" "$root/helper"
: > "$report"
exec > >(tee -a "$report") 2>&1
trap 'rc=$?; echo "diagnostic_exit=$rc"; exit "$rc"' EXIT

url=https://download.microsoft.com/download/8/E/9/8E9BBC64-E6F8-457C-9B8D-F6C9A16E6D6A/KB3AIK_EN.iso
head_end=16777215

echo '=== ISO filesystem metadata range ==='
curl -fsSL --retry 3 --connect-timeout 30 --max-time 600 \
  -H "Range: bytes=0-$head_end" \
  -D "$root/headers.txt" \
  -o "$root/KB3AIK_EN.head.bin" "$url"
cat "$root/headers.txt"
stat -c 'head_bytes=%s' "$root/KB3AIK_EN.head.bin"
printf 'head_sha256='; sha256sum "$root/KB3AIK_EN.head.bin" | cut -d ' ' -f 1

python3 - "$root/KB3AIK_EN.head.bin" "$root/winpe-range.txt" <<'PY'
import struct
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_bytes()
output = Path(sys.argv[2])
sector = 2048
pvd = source[16 * sector:17 * sector]
if len(pvd) != sector or pvd[0] != 1 or pvd[1:6] != b'CD001':
    raise SystemExit('ISO-9660 primary volume descriptor not found')
root_record_length = pvd[156]
root_record = pvd[156:156 + root_record_length]
if len(root_record) < 34:
    raise SystemExit('invalid ISO root directory record')
root_extent = struct.unpack_from('<I', root_record, 2)[0]
root_size = struct.unpack_from('<I', root_record, 10)[0]
root_start = root_extent * sector
root_end = root_start + root_size
if root_end > len(source):
    raise SystemExit(f'root directory is outside metadata range: end={root_end} bytes={len(source)}')

directory = source[root_start:root_end]
position = 0
found = None
while position < len(directory):
    length = directory[position]
    if length == 0:
        position = ((position // sector) + 1) * sector
        continue
    record = directory[position:position + length]
    if len(record) < 34:
        break
    extent = struct.unpack_from('<I', record, 2)[0]
    size = struct.unpack_from('<I', record, 10)[0]
    flags = record[25]
    name_length = record[32]
    raw_name = record[33:33 + name_length]
    name = raw_name.decode('ascii', errors='replace')
    normalized = name.upper().removesuffix(';1')
    if not (flags & 0x02) and normalized == 'WINPE.CAB':
        found = (name, extent, size)
        break
    position += length

if not found:
    entries = []
    position = 0
    while position < len(directory):
        length = directory[position]
        if length == 0:
            position = ((position // sector) + 1) * sector
            continue
        record = directory[position:position + length]
        if len(record) < 34:
            break
        name_length = record[32]
        entries.append(record[33:33 + name_length].decode('ascii', errors='replace'))
        position += length
    raise SystemExit('WinPE.cab not found in ISO root; entries=' + ','.join(entries))

name, extent, size = found
offset = extent * sector
end = offset + size - 1
output.write_text(f'{offset} {end} {size} {name}\n', encoding='utf-8')
print(f'iso_name={name}')
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
