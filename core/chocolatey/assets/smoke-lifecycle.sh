set -eu
echo "[cage] Prove Chocolatey local package lifecycle"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
choco_exe="$wine_prefix/drive_c/ProgramData/chocolatey/bin/choco.exe"
choco_exe_win='C:\ProgramData\chocolatey\bin\choco.exe'
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
smoke_feed_host="$bundle_root/build/chocolatey-smoke-feed"
smoke_nupkg="$smoke_feed_host/cage-chocolatey-smoke.0.1.0.nupkg"
smoke_json="$bundle_root/metadata/chocolatey-smoke.json"
diagnostic_json="$bundle_root/metadata/chocolatey-diagnostic.json"
policy_json="$bundle_root/metadata/chocolatey-feature-policy.json"
logs_dir="$bundle_root/logs/chocolatey-smoke"
sentinel="$wine_prefix/drive_c/ProgramData/Cage/chocolatey-smoke.sentinel"
install_evidence="$wine_prefix/drive_c/ProgramData/Cage/chocolatey-smoke-install.json"
uninstall_proof="$wine_prefix/drive_c/ProgramData/Cage/chocolatey-smoke-uninstall-proof.json"
mkdir -p "$smoke_feed_host" "$logs_dir" "$(dirname "$smoke_json")"
smoke_run_id="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
export CAGE_CHOCOLATEY_SMOKE_RUN_ID="$smoke_run_id"
unset WINEDLLOVERRIDES

python3 - "$smoke_nupkg" "{{SMOKE_NUPKG_BASE64}}" "{{SMOKE_NUPKG_SHA256}}" <<'PY'
import base64
import hashlib
import sys
from pathlib import Path
path = Path(sys.argv[1])
payload = base64.b64decode(sys.argv[2], validate=True)
expected = sys.argv[3]
actual = hashlib.sha256(payload).hexdigest()
if actual != expected:
    raise SystemExit(f"embedded smoke nupkg checksum mismatch: {actual} != {expected}")
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_bytes(payload)
temporary.replace(path)
PY
smoke_feed="$(winepath -w "$smoke_feed_host")"

# Remove any state from an interrupted prior proof before measuring this run.
set +e
timeout "${CAGE_CHOCOLATEY_SMOKE_TIMEOUT:-600s}" wine "$choco_exe_win" uninstall cage-chocolatey-smoke --source "$smoke_feed" --limit-output --no-progress -y > "$logs_dir/preclean-uninstall.log" 2>&1
rm -f "$sentinel" "$install_evidence" "$uninstall_proof"
wine reg delete 'HKCU\Environment' /v CAGE_CHOCOLATEY_SMOKE /f > "$logs_dir/preclean-marker.log" 2>&1
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" list --exact cage-chocolatey-smoke --limit-output > "$logs_dir/package-state-before.log" 2>&1
preclean_list_rc="$?"
grep -Eiq 'cage-chocolatey-smoke[| ]' "$logs_dir/package-state-before.log"
preclean_package_present_rc="$?"
test ! -f "$sentinel" && test ! -f "$install_evidence" && test ! -f "$uninstall_proof"
preclean_files_rc="$?"
wine reg query 'HKCU\Environment' /v CAGE_CHOCOLATEY_SMOKE > "$logs_dir/marker-absent-before.log" 2>&1
preclean_marker_query_rc="$?"
if [ "$preclean_list_rc" -eq 0 ] && [ "$preclean_package_present_rc" -ne 0 ] && [ "$preclean_files_rc" -eq 0 ] && [ "$preclean_marker_query_rc" -ne 0 ]; then
  preclean_rc=0
else
  preclean_rc=1
fi
set -e

set +e
test -f "$choco_exe"
canonical_exists_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" --version > "$logs_dir/choco-version-before.log" 2>&1
version_before_rc="$?"
test -f "$smoke_nupkg"
local_source_rc="$?"
timeout "${CAGE_CHOCOLATEY_SMOKE_TIMEOUT:-600s}" wine "$choco_exe_win" install cage-chocolatey-smoke --version 0.1.0 --source "$smoke_feed" --exact --limit-output --no-progress -y > "$logs_dir/install.log" 2>&1
install_rc="$?"
test -f "$sentinel"
sentinel_created_rc="$?"
wine reg query 'HKCU\Environment' /v CAGE_CHOCOLATEY_SMOKE > "$logs_dir/marker-installed.log" 2>&1
marker_created_rc="$?"
grep -Fq "$smoke_run_id" "$logs_dir/marker-installed.log"
marker_run_id_rc="$?"
test -f "$install_evidence"
powershell_evidence_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" list --exact cage-chocolatey-smoke --limit-output > "$logs_dir/package-state-installed.log" 2>&1
package_state_rc="$?"
grep -Eiq 'cage-chocolatey-smoke[| ]0\.1\.0' "$logs_dir/package-state-installed.log"
package_version_rc="$?"
timeout "${CAGE_CHOCOLATEY_SMOKE_TIMEOUT:-600s}" wine "$choco_exe_win" uninstall cage-chocolatey-smoke --source "$smoke_feed" --limit-output --no-progress -y > "$logs_dir/uninstall.log" 2>&1
uninstall_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" list --exact cage-chocolatey-smoke --limit-output > "$logs_dir/package-state-after.log" 2>&1
package_state_after_rc="$?"
grep -Eiq 'cage-chocolatey-smoke[| ]' "$logs_dir/package-state-after.log"
package_present_after_rc="$?"
if [ "$package_state_after_rc" -eq 0 ] && [ "$package_present_after_rc" -ne 0 ]; then package_removed_rc=0; else package_removed_rc=1; fi
test ! -f "$sentinel"
sentinel_removed_rc="$?"
wine reg query 'HKCU\Environment' /v CAGE_CHOCOLATEY_SMOKE > "$logs_dir/marker-removed.log" 2>&1
marker_query_after_rc="$?"
if [ "$marker_query_after_rc" -eq 0 ]; then marker_removed_rc=1; else marker_removed_rc=0; fi
test -f "$uninstall_proof"
uninstall_proof_rc="$?"
echo "[cage] Verify choco --version after uninstall"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" --version > "$logs_dir/choco-version-after.log" 2>&1
version_after_rc="$?"
set -e

python3 - "$smoke_json" "$install_evidence" "$uninstall_proof" "{{SMOKE_NUPKG_SHA256}}" "$smoke_run_id" "$preclean_rc" "$canonical_exists_rc" "$version_before_rc" "$local_source_rc" "$install_rc" "$sentinel_created_rc" "$marker_created_rc" "$marker_run_id_rc" "$powershell_evidence_rc" "$package_state_rc" "$package_version_rc" "$uninstall_rc" "$package_removed_rc" "$sentinel_removed_rc" "$marker_removed_rc" "$uninstall_proof_rc" "$version_after_rc" <<'PY'
import json
import sys
from pathlib import Path
(
    output_path, install_evidence_path, uninstall_proof_path, nupkg_sha256,
    smoke_run_id, preclean_rc, canonical_exists_rc, version_before_rc,
    local_source_rc, install_rc, sentinel_created_rc, marker_created_rc,
    marker_run_id_rc, powershell_evidence_rc, package_state_rc,
    package_version_rc, uninstall_rc, package_removed_rc, sentinel_removed_rc,
    marker_removed_rc, uninstall_proof_rc, version_after_rc,
) = sys.argv[1:]

def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}

install_evidence = load_json(install_evidence_path)
uninstall_proof = load_json(uninstall_proof_path)
powershell_boundary = all(
    install_evidence.get(key) not in (None, "")
    for key in ("PSVersion", "ProcessPath", "Is64BitProcess", "helperCommand")
)
current_run_evidence = (
    install_evidence.get("RunId") == smoke_run_id
    and uninstall_proof.get("RunId") == smoke_run_id
)
checks = {
    "initialStateClean": preclean_rc == "0",
    "canonicalChocoExists": canonical_exists_rc == "0",
    "chocoVersionBefore": version_before_rc == "0",
    "localSourceAvailable": local_source_rc == "0",
    "smokeInstall": install_rc == "0",
    "smokeSentinelCreated": sentinel_created_rc == "0",
    "smokeMarkerCreated": marker_created_rc == "0" and marker_run_id_rc == "0",
    "currentRunEvidence": current_run_evidence,
    "packagePowerShellBoundary": powershell_evidence_rc == "0" and powershell_boundary,
    "smokePackageState": package_state_rc == "0" and package_version_rc == "0",
    "smokeUninstall": uninstall_rc == "0",
    "smokePackageRemoved": package_removed_rc == "0",
    "smokeSentinelRemoved": sentinel_removed_rc == "0",
    "smokeMarkerRemoved": marker_removed_rc == "0",
    "uninstallLifecycle": uninstall_proof_rc == "0" and bool(uninstall_proof),
    "chocoVersionAfterUninstall": version_after_rc == "0",
}
passed = all(checks.values())
payload = {
    "schemaVersion": "cage.chocolatey-smoke/v0",
    "status": "passed" if passed else "failed",
    "runId": smoke_run_id,
    "package": {"name": "cage-chocolatey-smoke", "version": "0.1.0", "nupkgSha256": nupkg_sha256},
    "checks": checks,
    "installEvidence": install_evidence,
    "uninstallEvidence": uninstall_proof,
    "logs": {
        "install": "logs/chocolatey-smoke/install.log",
        "uninstall": "logs/chocolatey-smoke/uninstall.log",
        "packageState": "logs/chocolatey-smoke/package-state-installed.log",
        "packageStateAfter": "logs/chocolatey-smoke/package-state-after.log",
        "featurePolicy": "metadata/chocolatey-feature-policy.json",
    },
}
path = Path(output_path)
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY

python3 - "$diagnostic_json" "$smoke_json" "$policy_json" <<'PY'
import json
import sys
from pathlib import Path
diagnostic_path, smoke_path, policy_path = map(Path, sys.argv[1:])
diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
policy = json.loads(policy_path.read_text(encoding="utf-8"))
required = diagnostic.setdefault("tiers", {}).setdefault("required", {}).setdefault("checks", {})
required.update(smoke.get("checks", {}))
required["featurePolicy"] = policy.get("status") == "passed"
diagnostic.setdefault("checks", {}).update(smoke.get("checks", {}))
diagnostic["checks"]["featurePolicy"] = required["featurePolicy"]
failed = sorted(name for name, passed in required.items() if passed is not True)
diagnostic["tiers"]["required"]["status"] = "passed" if not failed else "failed"
diagnostic["failedChecks"] = failed
diagnostic["status"] = "passed" if not failed else "failed"
diagnostic["smokeEvidence"] = "metadata/chocolatey-smoke.json"
temporary = diagnostic_path.with_suffix(diagnostic_path.suffix + ".part")
temporary.write_text(json.dumps(diagnostic, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(diagnostic_path)
PY

smoke_status="$(python3 - "$smoke_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["status"])
PY
)"
if [ "$smoke_status" != "passed" ]; then
  echo "[cage] ERROR: local Chocolatey package lifecycle failed; see $smoke_json"
  cage_chocolatey_collect_failure_diagnostics "$diagnostic_json" "smoke-lifecycle"
  tail -120 "$logs_dir/install.log" || true
  tail -120 "$logs_dir/uninstall.log" || true
  exit 70
fi
echo "[cage] Chocolatey local package lifecycle passed"
