#!/usr/bin/env bash
# Prove that a real Windows pwsh.exe can execute through GE-Proton using the
# runtime's supported UMU entrypoint.
set -u

version="${POWERSHELL_VERSION:-7.4.11}"
out="${PROBE_OUTPUT_DIR:-/out}"
export WINEPREFIX="${WINEPREFIX:-/tmp/cage-proton-pwsh}"
export PROTONPATH="${PROTONPATH:-/opt/proton-ge}"
export GAMEID="${GAMEID:-umu-default}"
export STORE="${STORE:-none}"
export WINEDEBUG=-all
export PROTON_LOG=1
export UMU_LOG=1

archive="/tmp/PowerShell-${version}-win-x64.zip"
url="https://github.com/PowerShell/PowerShell/releases/download/v${version}/PowerShell-${version}-win-x64.zip"
pwsh_dir="$WINEPREFIX/drive_c/Program Files/PowerShell/7"
pwsh="$pwsh_dir/pwsh.exe"
script="$WINEPREFIX/drive_c/pwsh-proton-probe.ps1"
marker="$WINEPREFIX/drive_c/pwsh-proton-ok.txt"
policy_key='HKCU\Software\Wine\AppDefaults\pwsh.exe\DllOverrides'

mkdir -p "$out" "$WINEPREFIX"
record_rc() {
    printf '%s\n' "$2" > "$out/$1.rc"
}

if ! command -v umu-run > "$out/umu-path.log" 2>&1; then
    echo 'umu-run is not available' > "$out/error.log"
    exit 66
fi
if [ ! -d "$PROTONPATH" ]; then
    echo "missing Proton compatibility tool: $PROTONPATH" > "$out/error.log"
    exit 66
fi

# UMU creates and prepares WINEPREFIX before executing cmd.exe.
timeout --kill-after=20s 600s umu-run cmd.exe /d /s /c exit 0 \
    > "$out/prefix-init.log" 2>&1
rc=$?
record_rc prefix-init "$rc"
[ "$rc" -eq 0 ] || exit "$rc"
test -d "$WINEPREFIX/drive_c/windows/system32"

: > "$out/policy.log"
for override in 'amsi=' 'dwmapi=' 'rpcrt4=native,builtin'; do
    name="${override%%=*}"
    value="${override#*=}"
    timeout --kill-after=20s 300s umu-run reg.exe add "$policy_key" \
        /v "$name" /d "$value" /f >> "$out/policy.log" 2>&1
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
timeout --kill-after=20s 600s umu-run "$pwsh" \
    -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File 'C:\pwsh-proton-probe.ps1' 'C:\pwsh-proton-ok.txt' \
    > "$out/direct.log" 2>&1
direct_rc=$?
set -e
record_rc direct "$direct_rc"
tr -d '\r' < "$out/direct.log" > "$out/direct.normalized.log"
if [ -f "$marker" ]; then
    cp "$marker" "$out/marker.txt"
fi

if [ "$direct_rc" -eq 0 ] && \
   grep -Fqx "[diag] proton-version=$version" "$out/direct.normalized.log" && \
   [ -f "$marker" ] && [ "$(tr -d '\r\n' < "$marker")" = "$version" ]; then
    echo passed > "$out/result.txt"
    exit 0
fi

echo failed > "$out/result.txt"
find "$HOME" -maxdepth 3 -name 'steam-*.log' -type f -exec cp {} "$out/" \; 2>/dev/null || true
exit 99
