#!/usr/bin/env bash
# Diagnostic harness for identifying a Windows PowerShell Core build that
# produces real process effects under a Cage Wine runtime.
set -u

version="${POWERSHELL_VERSION:?POWERSHELL_VERSION is required}"
out="${PROBE_OUTPUT_DIR:-/out}"
export WINEPREFIX="${WINEPREFIX:-/tmp/cage-pwsh-${version}}"
export WINEARCH=win64
export WINEDEBUG=-all
export WINEDLLOVERRIDES="mscoree,mshtml="

archive="/tmp/PowerShell-${version}-win-x64.zip"
url="https://github.com/PowerShell/PowerShell/releases/download/v${version}/PowerShell-${version}-win-x64.zip"
pwsh_dir="$WINEPREFIX/drive_c/Program Files/PowerShell/7"
pwsh="$pwsh_dir/pwsh.exe"
marker="$WINEPREFIX/drive_c/pwsh-${version}-ok.txt"
script="$WINEPREFIX/drive_c/pwsh-${version}-probe.ps1"
policy_key='HKCU\Software\Wine\AppDefaults\pwsh.exe\DllOverrides'

mkdir -p "$out"
record_rc() {
    printf '%s\n' "$2" > "$out/$1.rc"
}

wineboot -u > "$out/wineboot.log" 2>&1
rc=$?
record_rc wineboot "$rc"
[ "$rc" -eq 0 ] || exit "$rc"
wineserver -w >> "$out/wineboot.log" 2>&1 || true

unset WINEDLLOVERRIDES
winecfg /v win10 > "$out/winecfg.log" 2>&1
rc=$?
record_rc winecfg "$rc"
[ "$rc" -eq 0 ] || exit "$rc"
wineserver -w >> "$out/winecfg.log" 2>&1 || true

: > "$out/policy.log"
for override in 'amsi=' 'dwmapi=' 'rpcrt4=native,builtin'; do
    name="${override%%=*}"
    value="${override#*=}"
    wine reg add "$policy_key" /v "$name" /d "$value" /f >> "$out/policy.log" 2>&1
    rc=$?
    [ "$rc" -eq 0 ] || exit "$rc"
done
wineserver -w >> "$out/policy.log" 2>&1 || true

curl -fL --retry 3 -o "$archive" "$url" > "$out/download.log" 2>&1
rc=$?
record_rc download "$rc"
[ "$rc" -eq 0 ] || exit "$rc"
sha256sum "$archive" > "$out/archive.sha256"

rm -rf "$pwsh_dir"
mkdir -p "$pwsh_dir"
unzip -q "$archive" -d "$pwsh_dir" > "$out/unzip.log" 2>&1
rc=$?
record_rc unzip "$rc"
[ "$rc" -eq 0 ] || exit "$rc"
chmod +x "$pwsh"

cat > "$script" <<'PS1'
param([Parameter(Mandatory = $true)][string]$Marker)
$ErrorActionPreference = 'Stop'
$version = $PSVersionTable.PSVersion.ToString()
[System.IO.File]::WriteAllText($Marker, $version)
[Console]::Out.WriteLine('[diag] version=' + $version)
PS1
script_win="$(winepath -w "$script")"
marker_win="$(winepath -w "$marker")"

set +e
timeout --kill-after=10s 180s wine "$pwsh" -NoLogo -NoProfile -NonInteractive \
    -ExecutionPolicy Bypass -File "$script_win" "$marker_win" \
    > "$out/direct.log" 2>&1
direct_rc=$?
timeout --kill-after=10s 60s wineserver -w >> "$out/direct.log" 2>&1
settle_rc=$?
set -e
record_rc direct "$direct_rc"
record_rc settle "$settle_rc"
tr -d '\r' < "$out/direct.log" > "$out/direct.normalized.log"
if [ -f "$marker" ]; then
    cp "$marker" "$out/marker.txt"
fi

if [ "$direct_rc" -eq 0 ] && [ "$settle_rc" -eq 0 ] && \
   grep -Fqx "[diag] version=$version" "$out/direct.normalized.log" && \
   [ -f "$marker" ] && [ "$(tr -d '\r\n' < "$marker")" = "$version" ]; then
    echo passed > "$out/result.txt"
    exit 0
fi

set +e
WINEDEBUG=+loaddll,+seh,+unwind timeout --kill-after=10s 180s \
    wine "$pwsh" -NoLogo -NoProfile -NonInteractive -Command \
    "[Console]::Out.WriteLine('[diag] winedebug=$version')" \
    > "$out/winedebug.stdout" 2> "$out/winedebug.stderr"
debug_rc=$?
set -e
record_rc winedebug "$debug_rc"
tail -240 "$out/winedebug.stderr" > "$out/winedebug.tail"
echo failed > "$out/result.txt"
exit 99
