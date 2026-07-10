# Failure-only Chocolatey evidence collector. Call only after a required check fails.
cage_chocolatey_collect_failure_diagnostics() {
  local diagnostic_json="$1"
  local failure_trigger="${2:-required-check}"
  local wine_prefix="${WINEPREFIX:-$HOME/.wine}"
  local choco_exe_win='C:\ProgramData\chocolatey\bin\choco.exe'
  local canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"
  local probe_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-diagnostics"
  local inventory_timeout="${CAGE_CHOCOLATEY_FAILURE_INVENTORY_TIMEOUT:-30s}"
  local inventory_limit="${CAGE_CHOCOLATEY_FAILURE_INVENTORY_LIMIT:-20000}"
  local loader_rc seh_rc promoted_rc registry_dump_rc process_tree_rc prefix_inventory_rc
  case "$inventory_limit" in
    ''|*[!0-9]*) echo "[cage] ERROR: invalid failure inventory limit: $inventory_limit" >&2; return 64 ;;
  esac
  mkdir -p "$probe_dir"
  set +e
  WINEDEBUG=+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe_win" --version > "$probe_dir/choco-mscoree-loader.log" 2>&1
  loader_rc="$?"
  WINEDEBUG=+seh,+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe_win" --version > "$probe_dir/choco-version-winedebug.log" 2>&1
  seh_rc="$?"
  timeout "$inventory_timeout" python3 - "$canonical_choco_dir" "$inventory_limit" > "$probe_dir/promoted-files.log" 2>&1 <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
limit = int(sys.argv[2])
count = 0
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    if count >= limit:
        print(f"[truncated after {limit} files]")
        break
    print(f"{path.stat().st_size}\t{path}")
    count += 1
PY
  promoted_rc="$?"
  timeout "$inventory_timeout" sh -c 'wine reg query "HKCU\Software\Wine" /s 2>&1 | head -n "$1"' sh "$inventory_limit" > "$probe_dir/registry-wine-dump.log" 2>&1
  registry_dump_rc="$?"
  timeout "$inventory_timeout" sh -c 'ps -eo pid,ppid,stat,comm,args --sort=pid 2>&1 | head -n "$1"' sh "$inventory_limit" > "$probe_dir/process-tree.log" 2>&1
  process_tree_rc="$?"
  timeout "$inventory_timeout" python3 - "$wine_prefix/drive_c" "$inventory_limit" > "$probe_dir/prefix-files.log" 2>&1 <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
limit = int(sys.argv[2])
count = 0
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    if count >= limit:
        print(f"[truncated after {limit} files]")
        break
    print(f"{path.stat().st_size}\t{path}")
    count += 1
PY
  prefix_inventory_rc="$?"
  set -e
  python3 - "$diagnostic_json" "$failure_trigger" "$loader_rc" "$seh_rc" "$promoted_rc" "$registry_dump_rc" "$process_tree_rc" "$prefix_inventory_rc" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
trigger = sys.argv[2]
loader_rc, seh_rc, promoted_rc, registry_dump_rc, process_tree_rc, prefix_inventory_rc = sys.argv[3:]
payload = json.loads(path.read_text(encoding="utf-8"))
payload.setdefault("tiers", {})["failureOnly"] = {
    "status": "run",
    "failureTrigger": trigger,
    "checks": {
        "mscoreeLoaderAttempted": loader_rc in {"0", "1", "124"},
        "sehTraceAttempted": seh_rc in {"0", "1", "124"},
        "promotedInventoryCaptured": promoted_rc == "0",
        "registryDumpCaptured": registry_dump_rc == "0",
        "processTreeCaptured": process_tree_rc == "0",
        "prefixInventoryCaptured": prefix_inventory_rc == "0",
    },
}
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY
}
