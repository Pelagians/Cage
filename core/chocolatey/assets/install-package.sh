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
policy_json="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-feature-policy.json"
mkdir -p "$logs_dir"
policy_status="$(python3 - "$policy_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("status", "failed"))
PY
)"
if [ "$policy_status" != "passed" ]; then
  echo "[cage] ERROR: refusing package install because Chocolatey feature policy did not pass: $policy_status"
  exit 70
fi
echo "[cage] Installing Chocolatey packages: {{PACKAGE_ARGS}}"
timeout "${CAGE_CHOCOLATEY_INSTALL_TIMEOUT:-1800s}" wine "$choco_exe_win" install {{PACKAGE_ARGS}} -y{{SOURCE_ARG}}
