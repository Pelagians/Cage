set -eu
echo "[cage] Apply Chocolatey feature policy"
choco_exe_win='C:\ProgramData\chocolatey\bin\choco.exe'
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
logs_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey"
policy_json="$metadata_dir/chocolatey-feature-policy.json"
diagnostic_json="$metadata_dir/chocolatey-diagnostic.json"
feature_list_log="$logs_dir/feature-list.log"
powershell_host_log="$logs_dir/disable-powershellHost.log"
powershell_host_policy='{{POWERSHELL_HOST_POLICY}}'
allow_global_confirmation_policy='{{ALLOW_GLOBAL_CONFIRMATION_POLICY}}'
mkdir -p "$metadata_dir" "$logs_dir"
unset WINEDLLOVERRIDES
if [ "$powershell_host_policy" != "disabled" ] || [ "$allow_global_confirmation_policy" != "disabled" ]; then
  echo "[cage] ERROR: unsupported Chocolatey feature policy in bootstrap profile" >&2
  exit 64
fi

set +e
timeout "${CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-120s}" wine "$choco_exe_win" feature disable --name={{POWERSHELL_HOST_FEATURE}} > "$powershell_host_log" 2>&1
powershell_host_disable_rc="$?"
timeout "${CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-120s}" wine "$choco_exe_win" feature list --limit-output > "$feature_list_log" 2>&1
feature_list_rc="$?"
grep -Eiq '^{{POWERSHELL_HOST_FEATURE}}\|false(\||$)' "$feature_list_log"
powershell_host_disabled_rc="$?"
grep -Eiq '^allowGlobalConfirmation\|false(\||$)' "$feature_list_log"
global_confirmation_disabled_rc="$?"
set -e

python3 - "$policy_json" "$diagnostic_json" "$powershell_host_policy" "$allow_global_confirmation_policy" "$powershell_host_disable_rc" "$feature_list_rc" "$powershell_host_disabled_rc" "$global_confirmation_disabled_rc" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
diagnostic_path = Path(sys.argv[2])
powershell_host_policy = sys.argv[3]
allow_global_confirmation_policy = sys.argv[4]
values = [int(value) for value in sys.argv[5:]]
passed = values[0] in {0, 2} and all(value == 0 for value in values[1:])
payload = {
    "schemaVersion": "cage.chocolatey-feature-policy/v0",
    "status": "passed" if passed else "failed",
    "features": {
        "powershellHost": powershell_host_policy if values[2] == 0 else "unknown",
        "allowGlobalConfirmation": allow_global_confirmation_policy if values[3] == 0 else "unknown",
    },
    "persistentGlobalConfirmationModified": False,
    "returnCodes": {
        "disablePowershellHost": values[0],
        "featureList": values[1],
    },
    "logs": {
        "powershellHost": "logs/chocolatey/disable-powershellHost.log",
        "featureList": "logs/chocolatey/feature-list.log",
    },
}
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
required = diagnostic.setdefault("tiers", {}).setdefault("required", {}).setdefault("checks", {})
required["featurePolicy"] = passed
diagnostic.setdefault("checks", {})["featurePolicy"] = passed
failed = sorted(name for name, value in required.items() if value is not True)
diagnostic["tiers"]["required"]["status"] = "passed" if not failed else "failed"
diagnostic["failedChecks"] = failed
diagnostic["status"] = "passed" if not failed else "failed"
diagnostic["featurePolicyEvidence"] = "metadata/chocolatey-feature-policy.json"
diagnostic_temporary = diagnostic_path.with_suffix(diagnostic_path.suffix + ".part")
diagnostic_temporary.write_text(
    json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
diagnostic_temporary.replace(diagnostic_path)
PY

policy_status="$(python3 - "$policy_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["status"])
PY
)"
if [ "$policy_status" != "passed" ]; then
  echo "[cage] Required Chocolatey feature policy failed; collecting failure-only diagnostics"
  cage_chocolatey_collect_failure_diagnostics "$diagnostic_json" "feature-policy"
  exit 70
fi

echo "[cage] Chocolatey feature policy applied"
