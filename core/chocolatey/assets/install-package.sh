set -eu
echo "[cage] Install Chocolatey packages"
choco_exe="${CFW_CHOCOLATEY_PREFIX_PATH:?CFW Chocolatey interface is missing}"
choco_exe_win="${CFW_CHOCOLATEY_WINDOWS_PATH:?CFW Chocolatey interface is missing}"
choco_launcher=("${CFW_CHOCOLATEY_PACKAGE_LAUNCHER:?CFW Chocolatey package launcher is missing}" "$choco_exe_win")
export ChocolateyInstall='C:\ProgramData\chocolatey'
export ChocolateyToolsLocation='C:\tools'
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
set +e
timeout "${CAGE_CHOCOLATEY_INSTALL_TIMEOUT:-1800s}" "${choco_launcher[@]}" install \
  {{PACKAGE_ARGS}} -y --use-system-powershell{{SOURCE_ARG}}
install_rc="$?"
timeout "${CAGE_CHOCOLATEY_SETTLE_TIMEOUT:-120s}" wineserver -w
settle_rc="$?"
lib_dir="$(dirname "$choco_exe")/lib"
evidence_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
helper_path="$(mktemp)"
printf '%s' '{{PACKAGE_EVIDENCE_HELPER_BASE64}}' | base64 -d > "$helper_path"
python3 "$helper_path" --lib "$lib_dir" --output "$evidence_dir/chocolatey-package-evidence.json" \
  --requested '{{REQUESTED_PACKAGES_JSON}}' --install-rc "$install_rc" --settle-rc "$settle_rc" \
  --source-url '{{PACKAGE_SOURCE}}'
query_rc="$?"
rm -f "$helper_path"
if [ "$install_rc" -ne 0 ]; then
  exit "$install_rc"
fi
if [ "$settle_rc" -ne 0 ]; then
  exit "$settle_rc"
fi
if [ "$query_rc" -ne 0 ]; then
  exit "$query_rc"
fi
set -e
echo "[cage] Chocolatey package install and evidence completed"
