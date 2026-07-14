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

echo '=== ISO/UDF metadata ranges ==='
curl -fsSL --retry 3 --connect-timeout 30 --max-time 600 \
  -H "Range: bytes=0-$head_end" \
  -D "$root/headers.txt" \
  -o "$root/KB3AIK_EN.head.bin" "$url"
cat "$root/headers.txt"
stat -c 'head_bytes=%s' "$root/KB3AIK_EN.head.bin"
printf 'head_sha256='; sha256sum "$root/KB3AIK_EN.head.bin" | cut -d ' ' -f 1

total_size="$(sed -nE 's/^content-range: bytes [0-9]+-[0-9]+\/([0-9]+)\r?$/\1/ip' "$root/headers.txt" | tail -1)"
test -n "$total_size"
tail_size=4194304
tail_start=$((total_size - tail_size))
tail_end=$((total_size - 1))
curl -fsSL --retry 3 --connect-timeout 30 --max-time 600 \
  -H "Range: bytes=$tail_start-$tail_end" \
  -D "$root/tail-headers.txt" \
  -o "$root/KB3AIK_EN.tail.bin" "$url"
stat -c 'tail_bytes=%s' "$root/KB3AIK_EN.tail.bin"
printf 'tail_sha256='; sha256sum "$root/KB3AIK_EN.tail.bin" | cut -d ' ' -f 1

truncate -s "$total_size" "$root/KB3AIK_EN.sparse.iso"
dd if="$root/KB3AIK_EN.head.bin" of="$root/KB3AIK_EN.sparse.iso" conv=notrunc status=none
dd if="$root/KB3AIK_EN.tail.bin" of="$root/KB3AIK_EN.sparse.iso" bs=1 seek="$tail_start" conv=notrunc status=none
stat -c 'sparse_iso_bytes=%s' "$root/KB3AIK_EN.sparse.iso"

python3 -m pip install --quiet pycdlib
python3 - "$root/KB3AIK_EN.sparse.iso" "$root/winpe-range.txt" <<'PY'
import sys
from pathlib import Path
import pycdlib

source = sys.argv[1]
output = Path(sys.argv[2])
iso = pycdlib.PyCdlib()
iso.open(source)
record = None
path = None
for dirname, _, filelist in iso.walk(udf_path='/'):
    for name in filelist:
        if name.upper() == 'WINPE.CAB':
            path = (dirname.rstrip('/') + '/' + name).replace('//', '/')
            record = iso.get_record(udf_path=path)
            break
    if record is not None:
        break
if record is None:
    iso.close()
    raise SystemExit('WinPE.cab not found in UDF filesystem')

print(f'udf_path={path}')
print(f'record_type={type(record).__module__}.{type(record).__name__}')
print(f'file_entry_extent={record.extent_location()}')
print(f'data_length={record.get_data_length()}')
print(f'icb_flags={record.icb_tag.flags}')
print(f'alloc_desc_count={len(record.alloc_descs)}')
for index, descriptor in enumerate(record.alloc_descs):
    print(f'alloc_desc[{index}]_type={type(descriptor).__module__}.{type(descriptor).__name__}')
    for name in ('log_block_num', 'extent_length', 'part_ref_num', 'partition_ref_num', 'extent_position'):
        if hasattr(descriptor, name):
            print(f'alloc_desc[{index}].{name}={getattr(descriptor, name)}')
    print(f'alloc_desc[{index}]_attrs=' + ','.join(
        name for name in dir(descriptor) if not name.startswith('_')
    ))

for attr_name in sorted(name for name in dir(iso) if 'udf' in name.lower() or 'part' in name.lower()):
    try:
        value = getattr(iso, attr_name)
    except Exception as exc:
        value = f'<error {exc}>'
    if callable(value):
        continue
    print(f'iso_attr.{attr_name}={value!r}')

iso.close()
raise SystemExit('allocation descriptor diagnostic complete')
PY

read -r offset end size udf_path < "$root/winpe-range.txt"
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
