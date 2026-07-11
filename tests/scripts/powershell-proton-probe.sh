#!/usr/bin/env bash
# Prove that a real Windows pwsh.exe can execute through GE-Proton.
set -u

version="${POWERSHELL_VERSION:-7.4.11}"
out="${PROBE_OUTPUT_DIR:-/out}"
proton="${PROTONPATH:-/opt/proton-ge}/proton"
export STEAM_COMPAT_DATA_PATH="${STEAM_COMPAT_DATA_PATH:-/tmp/cage-proton-pwsh}"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_COMPAT_CLIENT_INSTALL_PATH:-/tmp/steam}"
export PROTONPATH="${PROTONPATH:-/opt/proton-ge}"
export WINEDEBUG=-all
export PROTON_LOG=1
export GAMEID=0
export STORE=none

prefix="$STEAM_COMPAT_DATA_PATH/pfx"
archive="/tmp/PowerShell-${version}-win-x64.zip"
url="https://github.com/PowerShell/PowerShell/releases/download/v${version}/PowerShell-${version}-win-x64.zip"
pwsh_dir="$prefix/drive_c/Program Files/PowerShell/7"
pwsh="$pwsh_dir/pwsh.exe"
script="$prefix/drive_c/pwsh-proton-probe.ps1"
marker="$prefix/drive_c/pwsh-proton-ok.txt"

mkdir -p "$out" "$STEAM_COMPAT_DATA_PATH" "$STEAM_COMPAT_CLIENT_INSTALL_PATH"
record_rc() {
    printf '%s\n' "$2" > "$out/$1.rc"
}

if [ ! -x "$proton" ]; then
    echo "missing Proton launcher: $proton" > "$out/error.log"
    exit 66
fi

"$proton" runinprefix wineboot -u > "$out/wineboot.log" 2>&1
rc=$?
record_rc wineboot "$rc"
[ "$rc" -eq 0 ] || exit "$rc"
"$proton" runinprefix wineserver -w >> "$out/wineboot.log" 2>&1 || true

policy_key='HKCU\Software\Wine\AppDefaults\pwsh.exe\DllOverrides'
: > "$out/policy.log"
for override in 'amsi=' 'dwmapi=' 'rpcrt4=native,builtin'; do
    name="${override%%=*}"
    value="${override#*=}"
    "$proton" runinprefix reg add "$policy_key" /v "$name" /d "$value" /f >> "$out/policy.log" 2>&1
    rc=$?
    [ "$rc" -eq 0 ] || exit "$rc"
done

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
[Console]::Out.WriteLine('[diag] proton-version=' + $version)
PS1
rm -f "$marker"

set +e
timeout --kill-after=10s 240s "$proton" run "$pwsh" \
    -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File 'C:\pwsh-proton-probe.ps1' 'C:\pwsh-proton-ok.txt' \
    > "$out/direct.log" 2>&1
direct_rc=$?
timeout --kill-after=10s 90s "$proton" runinprefix wineserver -w >> "$out/direct.log" 2>&1
settle_rc=$?
set -e
record_rc direct "$direct_rc"
record_rc settle "$settle_rc"
tr -d '\r' < "$out/direct.log" > "$out/direct.normalized.log"
if [ -f "$marker" ]; then
    cp "$marker" "$out/marker.txt"
fi

if [ "$direct_rc" -eq 0 ] && [ "$settle_rc" -eq 0 ] && \
   grep -Fqx "[diag] proton-version=$version" "$out/direct.normalized.log" && \
   [ -f "$marker" ] && [ "$(tr -d '\r\n' < "$marker")" = "$version" ]; then
    echo passed > "$out/result.txt"
    exit 0
fi

echo failed > "$out/result.txt"
find "$HOME" -maxdepth 2 -name 'steam-*.log' -type f -exec cp {} "$out/" \; 2>/dev/null || true
exit 99
