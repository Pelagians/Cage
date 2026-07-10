set -eu
echo "[cage] Install Chocolatey packages"
choco_exe="${WINEPREFIX:-$HOME/.wine}/drive_c/ProgramData/chocolatey/bin/choco.exe"
choco_exe_win='C:\ProgramData\chocolatey\bin\choco.exe'
export ChocolateyInstall='C:\ProgramData\chocolatey'
export ChocolateyToolsLocation='C:\tools'
unset WINEDLLOVERRIDES
diagnostic_json="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-diagnostic.json"
if [ ! -f "$choco_exe" ]; then
  echo "[cage] ERROR: choco.exe is missing before package install: $choco_exe"
  exit 1
fi
choco_diag_status="$(python3 - "$diagnostic_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("status", "failed"))
PY
)"
if [ "$choco_diag_status" != "passed" ]; then
  echo "[cage] ERROR: refusing package install because Chocolatey diagnostics did not pass: $choco_diag_status"
  exit 69
fi
logs_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey"
mkdir -p "$logs_dir"
powershell_host_log="$logs_dir/chocolatey-feature-powershellHost.log"
global_confirmation_log="$logs_dir/chocolatey-feature-allowGlobalConfirmation.log"
echo "[cage] Applying upstream Chocolatey feature policy before package install..."
set +e
timeout "${CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-120s}" wine "$choco_exe_win" feature disable --name=powershellHost > "$powershell_host_log" 2>&1
powershell_host_rc="$?"
timeout "${CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-120s}" wine "$choco_exe_win" feature enable -n allowGlobalConfirmation > "$global_confirmation_log" 2>&1
global_confirmation_rc="$?"
set -e
if [ "$powershell_host_rc" -ne 0 ]; then
  echo "[cage] ERROR: failed to disable Chocolatey's built-in PowerShell host; see $powershell_host_log"
  tail -120 "$powershell_host_log" || true
  exit "$powershell_host_rc"
fi
if [ "$global_confirmation_rc" -ne 0 ]; then
  echo "[cage] ERROR: failed to enable Chocolatey global confirmation; see $global_confirmation_log"
  tail -120 "$global_confirmation_log" || true
  exit "$global_confirmation_rc"
fi
echo "[cage] Installing Chocolatey packages: {{PACKAGE_ARGS}}"
timeout "${CAGE_CHOCOLATEY_INSTALL_TIMEOUT:-1800s}" wine "$choco_exe_win" install {{PACKAGE_ARGS}} -y{{SOURCE_ARG}}
