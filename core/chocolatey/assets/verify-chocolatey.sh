set -eu
echo "[cage] Diagnose Chocolatey readiness"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
choco_exe="${CFW_CHOCOLATEY_PREFIX_PATH:?CFW Chocolatey interface is missing}"
choco_exe_win="${CFW_CHOCOLATEY_WINDOWS_PATH:?CFW Chocolatey interface is missing}"
choco_launcher=("${CFW_CHOCOLATEY_QUERY_LAUNCHER:?CFW Chocolatey query launcher is missing}" "$choco_exe_win")
probe_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-diagnostics"
diagnostic_json="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-diagnostic.json"
mkdir -p "$probe_dir" "$(dirname "$diagnostic_json")"
export ChocolateyInstall='C:\ProgramData\chocolatey'
export ChocolateyToolsLocation='C:\tools'

set +e
test -f "$choco_exe"; canonical_choco_rc="$?"
timeout --kill-after=15s "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-300s}" "${choco_launcher[@]}" --version > "$probe_dir/choco-version.log" 2>&1; choco_version_rc="$?"
timeout --kill-after=10s "${CAGE_CHOCOLATEY_VERIFY_SETTLE_TIMEOUT:-120s}" wineserver -w >> "$probe_dir/choco-version.log" 2>&1; choco_version_settle_rc="$?"
timeout --kill-after=15s "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-300s}" wine cmd /c "\"$choco_exe_win\" --version" > "$probe_dir/choco-version-cmd.log" 2>&1; choco_version_cmd_rc="$?"
timeout --kill-after=10s "${CAGE_CHOCOLATEY_VERIFY_SETTLE_TIMEOUT:-120s}" wineserver -w >> "$probe_dir/choco-version-cmd.log" 2>&1; choco_version_cmd_settle_rc="$?"
timeout --kill-after=15s "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-300s}" "${choco_launcher[@]}" source list > "$probe_dir/choco-source-list.log" 2>&1; choco_source_rc="$?"
timeout --kill-after=10s "${CAGE_CHOCOLATEY_VERIFY_SETTLE_TIMEOUT:-120s}" wineserver -w >> "$probe_dir/choco-source-list.log" 2>&1; choco_source_settle_rc="$?"
set -e

python3 - "$diagnostic_json" "$choco_exe" "$canonical_choco_rc" "$choco_version_rc" "$choco_version_settle_rc" "$choco_version_cmd_rc" "$choco_version_cmd_settle_rc" "$choco_source_rc" "$choco_source_settle_rc" <<'PY'
import json
import sys
from pathlib import Path
path, choco_exe, canonical_rc, version_rc, version_settle_rc, cmd_version_rc, cmd_version_settle_rc, source_rc, source_settle_rc = sys.argv[1:]
canonical = Path(choco_exe)
def ok(value): return value == "0"
required = {
    "canonicalChocoExists": ok(canonical_rc) and canonical.is_file(),
    "chocoVersion": ok(version_rc) and ok(version_settle_rc),
    "sourceList": ok(source_rc) and ok(source_settle_rc),
}
advisory = {"chocoVersionViaCmd": ok(cmd_version_rc) and ok(cmd_version_settle_rc)}
failed = sorted(name for name, passed in required.items() if not passed)
payload = {
    "schemaVersion": "cage.chocolatey-diagnostic/v0",
    "phase": "Chocolatey diagnostic",
    "status": "passed" if not failed else "failed",
    "failedChecks": failed,
    "returnCodes": {
        "chocoVersion": int(version_rc),
        "chocoVersionSettle": int(version_settle_rc),
        "chocoVersionViaCmd": int(cmd_version_rc),
        "chocoVersionViaCmdSettle": int(cmd_version_settle_rc),
        "sourceList": int(source_rc),
        "sourceListSettle": int(source_settle_rc),
    },
    "checks": {**required, **advisory},
    "tiers": {
        "required": {"status": "passed" if not failed else "failed", "checks": required},
        "advisory": {"status": "recorded", "checks": advisory},
        "failureOnly": {"status": "not-run", "checks": {}},
    },
    "paths": {"canonicalChoco": choco_exe, "logDirectory": "logs/chocolatey-diagnostics"},
    "logs": {
        "chocoVersion": "logs/chocolatey-diagnostics/choco-version.log",
        "chocoVersionViaCmd": "logs/chocolatey-diagnostics/choco-version-cmd.log",
        "sourceList": "logs/chocolatey-diagnostics/choco-source-list.log",
    },
}
temporary = Path(path).with_suffix(".json.part")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY

required_status="$(python3 - "$diagnostic_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["tiers"]["required"]["status"])
PY
)"
if [ "$required_status" != "passed" ]; then
  echo "[cage] Required Chocolatey checks failed; collecting failure-only diagnostics"
  cage_chocolatey_collect_failure_diagnostics "$diagnostic_json" "readiness"
  echo "[cage] ERROR: Chocolatey required diagnostics failed; see $diagnostic_json"
  tail -80 "$probe_dir/choco-version.log" || true
  exit 69
fi
echo "[cage] Chocolatey required diagnostics passed"
