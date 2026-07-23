set -eu
echo "[cage] Verify Chocolatey feature policy"
choco_exe_win="${CFW_CHOCOLATEY_WINDOWS_PATH:?CFW Chocolatey interface is missing}"
choco_launcher=(wine "$choco_exe_win")
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
logs_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey"
policy_json="$metadata_dir/chocolatey-feature-policy.json"
diagnostic_json="$metadata_dir/chocolatey-diagnostic.json"
feature_list_log="$logs_dir/feature-list.log"
powershell_host_policy='{{POWERSHELL_HOST_POLICY}}'
allow_global_confirmation_policy='{{ALLOW_GLOBAL_CONFIRMATION_POLICY}}'
mkdir -p "$metadata_dir" "$logs_dir"
if [ "$powershell_host_policy" != "disabled" ] || [ "$allow_global_confirmation_policy" != "disabled" ]; then
  echo "[cage] ERROR: unsupported Chocolatey feature policy in runtime profile" >&2
  exit 64
fi

set +e
timeout "${CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-120s}" "${choco_launcher[@]}" feature list --limit-output > "$feature_list_log" 2>&1
feature_list_rc="$?"
timeout "${CAGE_CHOCOLATEY_FEATURE_SETTLE_TIMEOUT:-120s}" wineserver -w >> "$feature_list_log" 2>&1
feature_list_settle_rc="$?"
set -e
normalized_log="$feature_list_log.normalized"
tr -d '\r' < "$feature_list_log" > "$normalized_log"
mv -f "$normalized_log" "$feature_list_log"
set +e
grep -Eiq '^{{POWERSHELL_HOST_FEATURE}}\|(disabled|false)(\||$)' "$feature_list_log"
powershell_host_disabled_rc="$?"
grep -Eiq '^allowGlobalConfirmation\|(disabled|false)(\||$)' "$feature_list_log"
global_confirmation_disabled_rc="$?"
set -e

python3 - "$policy_json" "$diagnostic_json" "$powershell_host_policy" "$allow_global_confirmation_policy" "$feature_list_rc" "$feature_list_settle_rc" "$powershell_host_disabled_rc" "$global_confirmation_disabled_rc" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
diagnostic_path = Path(sys.argv[2])
powershell_host_policy = sys.argv[3]
allow_global_confirmation_policy = sys.argv[4]
values = [int(value) for value in sys.argv[5:]]
passed = all(value == 0 for value in values)
payload = {
    "schemaVersion": "cage.chocolatey-feature-policy/v0",
    "status": "passed" if passed else "failed",
    "features": {
        "powershellHost": powershell_host_policy if values[2] == 0 else "unknown",
        "allowGlobalConfirmation": allow_global_confirmation_policy if values[3] == 0 else "unknown",
    },
    "persistentGlobalConfirmationModified": False,
    "returnCodes": {
        "featureList": values[0],
        "featureListSettle": values[1],
    },
    "logs": {
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

echo "[cage] Chocolatey feature policy verified"
