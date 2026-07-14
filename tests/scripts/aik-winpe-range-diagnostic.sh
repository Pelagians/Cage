#!/usr/bin/env bash
set -euo pipefail

root=/tmp/aik-expand
report="$root/report.txt"
mkdir -p "$root/winpe" "$root/helper"
: > "$report"
exec > >(tee -a "$report") 2>&1
trap 'rc=$?; echo "diagnostic_exit=$rc"; exit "$rc"' EXIT

url=https://download.microsoft.com/download/8/E/9/8E9BBC64-E6F8-457C-9B8D-F6C9A16E6D6A/KB3AIK_EN.iso
offset=640526336
end=1086964920
size=446438585

echo '=== direct WinPE.cab range ==='
echo "winpe_offset=$offset"
echo "winpe_end=$end"
echo "winpe_size=$size"
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
