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
# Match Cage builder prefix initialization: keep Wine's default mscoree/mshtml
# suppression during wineboot to avoid Mono/HTML setup hangs, then clear it
# before .NET/PowerShell MSI work so CoreCLR dependencies can resolve.
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-mscoree,mshtml=}"

log_file() {
  local prefix="$1" file="$2"
  if [ -s "$file" ]; then
    sed "s/^/[${prefix}] /" "$file"
  else
    echo "[cage-pwsh-smoke] ${file} was empty"
  fi
}

file_bytes() {
  local file="$1"
  if [ -f "$file" ]; then
    wc -c < "$file" | tr -d ' '
  else
    echo 0
  fi
}

file_b64_preview() {
  local file="$1"
  if [ -f "$file" ] && [ -s "$file" ]; then
    head -c "${CAGE_ANNOTATION_PREVIEW_BYTES:-768}" "$file" | base64 -w0
  else
    echo empty
  fi
}

file_state() {
  local file="$1"
  if [ -f "$file" ]; then
    echo present
  else
    echo missing
  fi
}

github_error() {
  local title="$1" message="$2"
  if [ -n "${GITHUB_ACTIONS:-}" ] || [ -n "${CAGE_GITHUB_ANNOTATIONS:-}" ]; then
    echo "::error title=${title}::${message}"
  fi
}

launch_failure_message() {
  local mode="$1" rc="$2" reason="$3" stdout_file="$4" stderr_file="$5"
  printf 'mode=%s rc=%s reason=%s sentinel=%s output=%s stdout_bytes=%s stderr_bytes=%s output_bytes=%s stdout_b64=%s stderr_b64=%s output_b64=%s pwsh=%s script=%s' \
    "$mode" "$rc" "$reason" \
    "$(file_state "$SMOKE_SENTINEL")" \
    "$(file_state "$SMOKE_OUTPUT")" \
    "$(file_bytes "$stdout_file")" \
    "$(file_bytes "$stderr_file")" \
    "$(file_bytes "$SMOKE_OUTPUT")" \
    "$(file_b64_preview "$stdout_file")" \
    "$(file_b64_preview "$stderr_file")" \
    "$(file_b64_preview "$SMOKE_OUTPUT")" \
    "$PWSH_EXE_WIN" "$SMOKE_SCRIPT_WIN"
}

reg_add_pwsh_override() {
  local name="$1" value="$2"
  local stdout_file="$CAPTURE_DIR/reg-${name}.stdout"
  local stderr_file="$CAPTURE_DIR/reg-${name}.stderr"
  local key='HKCU\Software\Wine\AppDefaults\pwsh.exe\DllOverrides'

  echo "[cage-pwsh-smoke] Adding pwsh.exe DLL override: ${name}=${value:-<empty>}"
  set +e
  timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" \
    wine reg add "$key" /v "$name" /d "$value" /f \
      > "$stdout_file" 2> "$stderr_file"
  local rc="$?"
  set -e

  echo "[cage-pwsh-smoke] DLL override ${name} registry rc=${rc}"
  log_file "cage-pwsh-reg-${name}-out" "$stdout_file"
  log_file "cage-pwsh-reg-${name}-err" "$stderr_file"

  if [ "$rc" -ne 0 ]; then
    github_error "PowerShell DLL override registry prep failed" \
      "override=$name value=${value:-<empty>} rc=$rc stdout_bytes=$(file_bytes "$stdout_file") stderr_bytes=$(file_bytes "$stderr_file") stdout_b64=$(file_b64_preview "$stdout_file") stderr_b64=$(file_b64_preview "$stderr_file") key=$key"
    exit "$rc"
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
        wine cmd /s /c "call \"$PWSH_EXE_WIN\" -NoLogo -NoProfile -ExecutionPolicy Bypass -File \"$SMOKE_SCRIPT_WIN\" \"$SMOKE_SENTINEL_WIN\" \"$SMOKE_OUTPUT_WIN\"" \
          > "$stdout_file" 2> "$stderr_file"
      ;;
    cmdfile)
      timeout "${CAGE_POWERSHELL_SMOKE_TIMEOUT:-120s}" \
        wine cmd /s /c "$SMOKE_LAUNCHER_WIN" \
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
    github_error "PowerShell launch failed" "$(launch_failure_message "$mode" "$rc" "nonzero-exit" "$stdout_file" "$stderr_file")"
    return 1
  fi
  if [ ! -f "$SMOKE_SENTINEL" ]; then
    echo "[cage-pwsh-smoke] ${mode} did not create sentinel: $SMOKE_SENTINEL"
    github_error "PowerShell launch failed" "$(launch_failure_message "$mode" "$rc" "missing-sentinel" "$stdout_file" "$stderr_file")"
    return 1
  fi
  if ! grep -q 'PWSH-ALIVE' "$stdout_file" && ! grep -q 'PWSH-ALIVE' "$SMOKE_OUTPUT" 2>/dev/null; then
    echo "[cage-pwsh-smoke] ${mode} created sentinel but did not produce PWSH-ALIVE evidence"
    github_error "PowerShell launch failed" "$(launch_failure_message "$mode" "$rc" "missing-pwsh-alive" "$stdout_file" "$stderr_file")"
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
echo "[cage-pwsh-smoke] wineboot DLL override policy: ${WINEDLLOVERRIDES:-<empty>}"
timeout "${CAGE_WINEBOOT_TIMEOUT:-300s}" wine wineboot --init >/tmp/cage-pwsh-wineboot.stdout 2>/tmp/cage-pwsh-wineboot.stderr || {
  rc="$?"
  echo "[cage-pwsh-smoke] wineboot failed: $rc"
  github_error "Wine prefix initialization failed" "rc=$rc display=${DISPLAY:-<unset>} stdout_bytes=$(file_bytes /tmp/cage-pwsh-wineboot.stdout) stderr_bytes=$(file_bytes /tmp/cage-pwsh-wineboot.stderr) prefix=$PREFIX dll_overrides=${WINEDLLOVERRIDES:-<empty>}"
  log_file cage-wineboot-out /tmp/cage-pwsh-wineboot.stdout
  log_file cage-wineboot-err /tmp/cage-pwsh-wineboot.stderr
  echo "[cage-pwsh-smoke] DISPLAY=${DISPLAY:-<unset>}"
  xdpyinfo -display "${DISPLAY:-:99}" >/tmp/cage-pwsh-xdpyinfo.stdout 2>/tmp/cage-pwsh-xdpyinfo.stderr || true
  log_file cage-xdpyinfo-out /tmp/cage-pwsh-xdpyinfo.stdout
  log_file cage-xdpyinfo-err /tmp/cage-pwsh-xdpyinfo.stderr
  ps -ef | grep -Ei 'wine|wineserver|xvfb' | grep -v grep | sed 's/^/[cage-pwsh-process] /' || true
  find "$PREFIX" -maxdepth 3 -printf '[cage-pwsh-prefix] %p\n' 2>/dev/null | head -80 || true
  exit "$rc"
}
wineserver -w || true

# Clear the image's prefix-init DLL policy before PowerShell/.NET work.
export WINEDLLOVERRIDES=""

echo "[cage-pwsh-smoke] Setting prefix to win10"
timeout "${CAGE_WINECFG_TIMEOUT:-120s}" winecfg /v win10 >/tmp/cage-pwsh-winecfg.stdout 2>/tmp/cage-pwsh-winecfg.stderr || {
  rc="$?"
  echo "[cage-pwsh-smoke] winecfg failed: $rc"
  github_error "Wine win10 configuration failed" "rc=$rc stdout_bytes=$(file_bytes /tmp/cage-pwsh-winecfg.stdout) stderr_bytes=$(file_bytes /tmp/cage-pwsh-winecfg.stderr) prefix=$PREFIX"
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
  github_error "PowerShell MSI checksum mismatch" "expected=$POWERSHELL_SHA256 actual=$actual_sha path=$MSI_PATH"
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
  github_error "PowerShell MSI did not install pwsh.exe" "msi_rc=$msi_rc expected=$PWSH_EXE log_bytes=$(file_bytes "$MSI_LOG") prefix=$PREFIX"
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

echo "[cage-pwsh-smoke] Preparing pwsh.exe Wine DLL overrides"
reg_add_pwsh_override amsi ""
reg_add_pwsh_override dwmapi ""
reg_add_pwsh_override rpcrt4 native,builtin
wineserver -w || true

SMOKE_DIR="$WINEPREFIX/drive_c/ProgramData/CagePowerShellSmoke"
SMOKE_DIR_WIN='C:/ProgramData/CagePowerShellSmoke'
SMOKE_SCRIPT="$SMOKE_DIR/smoke.ps1"
SMOKE_SCRIPT_WIN="$SMOKE_DIR_WIN/smoke.ps1"
SMOKE_SENTINEL="$SMOKE_DIR/cage-pwsh-smoke-ok.txt"
SMOKE_SENTINEL_WIN="$SMOKE_DIR_WIN/cage-pwsh-smoke-ok.txt"
SMOKE_OUTPUT="$SMOKE_DIR/cage-pwsh-smoke-output.txt"
SMOKE_OUTPUT_WIN="$SMOKE_DIR_WIN/cage-pwsh-smoke-output.txt"
SMOKE_LAUNCHER="$SMOKE_DIR/run-smoke.cmd"
SMOKE_LAUNCHER_WIN="$SMOKE_DIR_WIN/run-smoke.cmd"
mkdir -p "$SMOKE_DIR"
cat > "$SMOKE_SCRIPT" <<'PS1'
param([string]$SentinelPath, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
[Console]::Out.WriteLine('PWSH-ALIVE')
[System.IO.File]::WriteAllText($SentinelPath, 'ok')
[System.IO.File]::WriteAllText($OutputPath, 'PWSH-ALIVE')
[Console]::Out.WriteLine('[cage-pwsh-smoke] PSVersion=' + $PSVersionTable.PSVersion.ToString())
PS1
printf '@echo off\r\ncall "%s" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%s" "%s" "%s"\r\nexit /b %%ERRORLEVEL%%\r\n' \
  "$PWSH_EXE_WIN" "$SMOKE_SCRIPT_WIN" "$SMOKE_SENTINEL_WIN" "$SMOKE_OUTPUT_WIN" \
  > "$SMOKE_LAUNCHER"

echo "[cage-pwsh-smoke] WINEPREFIX dosdevices"
ls -la "$WINEPREFIX/dosdevices" || true

echo "[cage-pwsh-smoke] cmd baseline"
wine cmd /c "echo CMD-ALIVE" > "$CAPTURE_DIR/cmd.stdout" 2> "$CAPTURE_DIR/cmd.stderr" || true
log_file cage-cmd-out "$CAPTURE_DIR/cmd.stdout"
log_file cage-cmd-err "$CAPTURE_DIR/cmd.stderr"

if try_pwsh_launch direct || try_pwsh_launch cmd || try_pwsh_launch cmdfile; then
  echo "[cage-pwsh-smoke] POWER SHELL RUNTIME SMOKE PASSED"
  exit 0
fi

echo "[cage-pwsh-smoke] ERROR: no PowerShell launch mode produced stdout/sentinel evidence"
github_error "No PowerShell launch mode produced runtime proof" "direct, cmd, and cmdfile launch modes failed; inspect PowerShell launch failed annotations; smoke_dir=$SMOKE_DIR capture_dir=$CAPTURE_DIR pwsh=$PWSH_EXE_WIN script=$SMOKE_SCRIPT_WIN launcher=$SMOKE_LAUNCHER_WIN"
echo "[cage-pwsh-smoke] Smoke directory: $SMOKE_DIR"
find "$SMOKE_DIR" -maxdepth 1 -type f -printf '[cage-pwsh-smoke] C-drive file: %f\n' 2>/dev/null || true
echo "[cage-pwsh-smoke] Capture directory: $CAPTURE_DIR"
find "$CAPTURE_DIR" -maxdepth 1 -type f -printf '[cage-pwsh-smoke] capture file: %f\n' 2>/dev/null || true
exit 99
