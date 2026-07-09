#!/usr/bin/env bash
# Prove that a Cage Wine runtime can execute Windows PowerShell 7 for real.
# This is intentionally independent of the Chocolatey module: Chocolatey must
# not be the first place we learn whether pwsh.exe can create process effects.

set -euo pipefail

POWERSHELL_VERSION="${CAGE_POWERSHELL_VERSION:-7.5.5}"
POWERSHELL_MSI="${CAGE_POWERSHELL_MSI:-PowerShell-7.5.5-win-x64.msi}"
POWERSHELL_URL="https://github.com/PowerShell/PowerShell/releases/download/v${POWERSHELL_VERSION}/${POWERSHELL_MSI}"
POWERSHELL_SHA256="b2ac56b7639e2b259bb78bab077555d76f2a5eec6c516690d63de36bc1d6ca25"
POWERSHELL_PRODUCT_KEY='HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\{634F4903-28DC-4BA6-A39F-4B3E394D4E36}'

PREFIX="${CAGE_POWERSHELL_SMOKE_PREFIX:-/tmp/cage-pwsh-smoke-prefix}"
CACHE="${CAGE_POWERSHELL_SMOKE_CACHE:-/tmp/cage-pwsh-smoke-cache}"
CAPTURE_DIR="$(mktemp -d /tmp/cage-pwsh-runtime-smoke.XXXXXX)"

export WINEPREFIX="$PREFIX"
export WINEARCH="${WINEARCH:-win64}"
export WINEDEBUG="${WINEDEBUG:--all}"
unset WINEDLLOVERRIDES

log_file() {
  local prefix="$1" file="$2"
  if [ -s "$file" ]; then
    sed "s/^/[${prefix}] /" "$file"
  else
    echo "[cage-pwsh-smoke] ${file} was empty"
  fi
}

try_pwsh_launch() {
  local mode="$1"
  local stdout_file="$CAPTURE_DIR/${mode}.stdout"
  local stderr_file="$CAPTURE_DIR/${mode}.stderr"

  rm -f "$SMOKE_SENTINEL" "$SMOKE_OUTPUT" "$stdout_file" "$stderr_file"
  echo "[cage-pwsh-smoke] Trying PowerShell launch mode: ${mode}"

  set +e
  case "$mode" in
    direct)
      timeout "${CAGE_POWERSHELL_SMOKE_TIMEOUT:-120s}" \
        wine "$PWSH_EXE_WIN" -NoLogo -NoProfile -ExecutionPolicy Bypass \
          -File "$SMOKE_SCRIPT_WIN" "$SMOKE_SENTINEL_WIN" "$SMOKE_OUTPUT_WIN" \
          > "$stdout_file" 2> "$stderr_file"
      ;;
    cmd)
      timeout "${CAGE_POWERSHELL_SMOKE_TIMEOUT:-120s}" \
        wine cmd /s /c "\"$PWSH_EXE_WIN\" -NoLogo -NoProfile -ExecutionPolicy Bypass -File \"$SMOKE_SCRIPT_WIN\" \"$SMOKE_SENTINEL_WIN\" \"$SMOKE_OUTPUT_WIN\"" \
          > "$stdout_file" 2> "$stderr_file"
      ;;
    *)
      echo "[cage-pwsh-smoke] Unknown launch mode: ${mode}" >&2
      return 2
      ;;
  esac
  local rc="$?"
  set -e

  echo "[cage-pwsh-smoke] ${mode} exit code: ${rc}"
  log_file "cage-pwsh-${mode}-out" "$stdout_file"
  log_file "cage-pwsh-${mode}-err" "$stderr_file"

  if [ "$rc" -ne 0 ]; then
    return 1
  fi
  if [ ! -f "$SMOKE_SENTINEL" ]; then
    echo "[cage-pwsh-smoke] ${mode} did not create sentinel: $SMOKE_SENTINEL"
    return 1
  fi
  if ! grep -q 'PWSH-ALIVE' "$stdout_file" && ! grep -q 'PWSH-ALIVE' "$SMOKE_OUTPUT" 2>/dev/null; then
    echo "[cage-pwsh-smoke] ${mode} created sentinel but did not produce PWSH-ALIVE evidence"
    return 1
  fi

  echo "[cage-pwsh-smoke] POWER SHELL RUNTIME SMOKE PASSED via ${mode}"
  return 0
}

echo "[cage-pwsh-smoke] Starting PowerShell runtime smoke"
echo "[cage-pwsh-smoke] wine: $(wine --version)"
echo "[cage-pwsh-smoke] WINEPREFIX=$WINEPREFIX"
echo "[cage-pwsh-smoke] capture=$CAPTURE_DIR"

rm -rf "$PREFIX"
mkdir -p "$PREFIX" "$CACHE"

echo "[cage-pwsh-smoke] Initializing fresh Wine prefix"
timeout "${CAGE_WINEBOOT_TIMEOUT:-180s}" wineboot --init >/tmp/cage-pwsh-wineboot.stdout 2>/tmp/cage-pwsh-wineboot.stderr || {
  rc="$?"
  echo "[cage-pwsh-smoke] wineboot failed: $rc"
  log_file cage-wineboot-out /tmp/cage-pwsh-wineboot.stdout
  log_file cage-wineboot-err /tmp/cage-pwsh-wineboot.stderr
  exit "$rc"
}
wineserver -w || true

echo "[cage-pwsh-smoke] Setting prefix to win10"
timeout "${CAGE_WINECFG_TIMEOUT:-120s}" winecfg /v win10 >/tmp/cage-pwsh-winecfg.stdout 2>/tmp/cage-pwsh-winecfg.stderr || {
  rc="$?"
  echo "[cage-pwsh-smoke] winecfg failed: $rc"
  log_file cage-winecfg-out /tmp/cage-pwsh-winecfg.stdout
  log_file cage-winecfg-err /tmp/cage-pwsh-winecfg.stderr
  exit "$rc"
}
wineserver -w || true

MSI_PATH="$CACHE/$POWERSHELL_MSI"
if [ ! -f "$MSI_PATH" ]; then
  echo "[cage-pwsh-smoke] Downloading ${POWERSHELL_MSI}"
  curl -fL --retry 3 -o "$MSI_PATH" "$POWERSHELL_URL"
fi
actual_sha="$(sha256sum "$MSI_PATH" | cut -d ' ' -f 1)"
if [ "$actual_sha" != "$POWERSHELL_SHA256" ]; then
  echo "[cage-pwsh-smoke] ERROR: PowerShell MSI checksum mismatch"
  echo "[cage-pwsh-smoke] expected=$POWERSHELL_SHA256"
  echo "[cage-pwsh-smoke] actual=$actual_sha"
  exit 64
fi

MSI_WIN="$(winepath -w "$MSI_PATH")"
MSI_LOG="$CAPTURE_DIR/powershell-msiexec.log"
MSI_LOG_WIN="$(winepath -w "$MSI_LOG")"

echo "[cage-pwsh-smoke] Installing ${POWERSHELL_MSI}"
set +e
timeout "${CAGE_POWERSHELL_MSI_TIMEOUT:-1200s}" \
  wine msiexec /i "$MSI_WIN" \
    DISABLE_TELEMETRY=1 ENABLE_PSREMOTING=1 REGISTER_MANIFEST=1 \
    MSIFASTINSTALL=2 DISABLEROLLBACK=1 MSIDISABLEEEUI=1 \
    USE_MU=0 ENABLE_MU=0 /QN /NORESTART /L*v "$MSI_LOG_WIN"
msi_rc="$?"
set -e
if [ -f "$MSI_LOG" ]; then
  grep -nEi 'Return value 3|MainEngineThread|Error [0-9]+|Fatal error' "$MSI_LOG" | head -80 | sed 's/^/[cage-pwsh-msi-marker] /' || true
  tail -120 "$MSI_LOG" | sed 's/^/[cage-pwsh-msi] /'
fi
if [ "$msi_rc" -ne 0 ]; then
  echo "[cage-pwsh-smoke] PowerShell MSI Wine exit code: $msi_rc"
fi

PWSH_EXE="$WINEPREFIX/drive_c/Program Files/PowerShell/7/pwsh.exe"
if [ ! -f "$PWSH_EXE" ]; then
  echo "[cage-pwsh-smoke] ERROR: MSI did not install pwsh.exe: $PWSH_EXE"
  exit 65
fi
chmod +x "$PWSH_EXE"
PWSH_EXE_WIN="$(winepath -w "$PWSH_EXE")"

echo "[cage-pwsh-smoke] pwsh_exe_win=$PWSH_EXE_WIN"
set +e
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg query "$POWERSHELL_PRODUCT_KEY" >/tmp/cage-pwsh-reg.stdout 2>/tmp/cage-pwsh-reg.stderr
reg_rc="$?"
set -e
echo "[cage-pwsh-smoke] PowerShell product registry query rc=$reg_rc"
log_file cage-pwsh-reg-out /tmp/cage-pwsh-reg.stdout
log_file cage-pwsh-reg-err /tmp/cage-pwsh-reg.stderr

SMOKE_DIR="$WINEPREFIX/drive_c/ProgramData/CagePowerShellSmoke"
SMOKE_DIR_WIN='C:/ProgramData/CagePowerShellSmoke'
SMOKE_SCRIPT="$SMOKE_DIR/smoke.ps1"
SMOKE_SCRIPT_WIN="$SMOKE_DIR_WIN/smoke.ps1"
SMOKE_SENTINEL="$SMOKE_DIR/cage-pwsh-smoke-ok.txt"
SMOKE_SENTINEL_WIN="$SMOKE_DIR_WIN/cage-pwsh-smoke-ok.txt"
SMOKE_OUTPUT="$SMOKE_DIR/cage-pwsh-smoke-output.txt"
SMOKE_OUTPUT_WIN="$SMOKE_DIR_WIN/cage-pwsh-smoke-output.txt"
mkdir -p "$SMOKE_DIR"
cat > "$SMOKE_SCRIPT" <<'PS1'
param([string]$SentinelPath, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
[Console]::Out.WriteLine('PWSH-ALIVE')
[System.IO.File]::WriteAllText($SentinelPath, 'ok')
[System.IO.File]::WriteAllText($OutputPath, 'PWSH-ALIVE')
[Console]::Out.WriteLine('[cage-pwsh-smoke] PSVersion=' + $PSVersionTable.PSVersion.ToString())
PS1

echo "[cage-pwsh-smoke] WINEPREFIX dosdevices"
ls -la "$WINEPREFIX/dosdevices" || true

echo "[cage-pwsh-smoke] cmd baseline"
wine cmd /c "echo CMD-ALIVE" > "$CAPTURE_DIR/cmd.stdout" 2> "$CAPTURE_DIR/cmd.stderr" || true
log_file cage-cmd-out "$CAPTURE_DIR/cmd.stdout"
log_file cage-cmd-err "$CAPTURE_DIR/cmd.stderr"

if try_pwsh_launch direct || try_pwsh_launch cmd; then
  echo "[cage-pwsh-smoke] POWER SHELL RUNTIME SMOKE PASSED"
  exit 0
fi

echo "[cage-pwsh-smoke] ERROR: no PowerShell launch mode produced stdout/sentinel evidence"
echo "[cage-pwsh-smoke] Smoke directory: $SMOKE_DIR"
find "$SMOKE_DIR" -maxdepth 1 -type f -printf '[cage-pwsh-smoke] C-drive file: %f\n' 2>/dev/null || true
echo "[cage-pwsh-smoke] Capture directory: $CAPTURE_DIR"
find "$CAPTURE_DIR" -maxdepth 1 -type f -printf '[cage-pwsh-smoke] capture file: %f\n' 2>/dev/null || true
exit 99
