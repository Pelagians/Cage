# Failure-only Chocolatey evidence collector. Call only after a required check fails.
cage_chocolatey_collect_failure_diagnostics() {
  local diagnostic_json="$1"
  local failure_trigger="${2:-required-check}"
  local wine_prefix="${WINEPREFIX:-$HOME/.wine}"
  local choco_exe_win="${CFW_CHOCOLATEY_WINDOWS_PATH:?CFW Chocolatey interface is missing}"
  local -a choco_launcher=("${CFW_CHOCOLATEY_QUERY_LAUNCHER:?CFW Chocolatey query launcher is missing}" "$choco_exe_win")
  local canonical_choco_dir
  canonical_choco_dir="$(dirname "${CFW_CHOCOLATEY_PREFIX_PATH:?CFW Chocolatey interface is missing}")"
  local probe_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-diagnostics"
  local inventory_timeout="${CAGE_CHOCOLATEY_FAILURE_INVENTORY_TIMEOUT:-30s}"
  local inventory_limit="${CAGE_CHOCOLATEY_FAILURE_INVENTORY_LIMIT:-20000}"
  local live_snapshot_delay="${CAGE_CHOCOLATEY_LIVE_SNAPSHOT_DELAY:-2}"
  local loader_rc seh_rc live_probe_rc live_process_tree_rc promoted_rc registry_dump_rc process_tree_rc prefix_inventory_rc
  case "$inventory_limit" in
    ''|*[!0-9]*) echo "[cage] ERROR: invalid failure inventory limit: $inventory_limit" >&2; return 64 ;;
  esac
  mkdir -p "$probe_dir"
  set +e
  WINEDEBUG=+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-15s}" "${choco_launcher[@]}" --version > "$probe_dir/choco-mscoree-loader.log" 2>&1
  loader_rc="$?"
  WINEDEBUG=+seh,+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-15s}" "${choco_launcher[@]}" --version > "$probe_dir/choco-version-winedebug.log" 2>&1
  seh_rc="$?"
  timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-15s}" "${choco_launcher[@]}" --version > "$probe_dir/choco-live-probe.log" 2>&1 &
  live_probe_pid="$!"
  sleep "$live_snapshot_delay"
  timeout "$inventory_timeout" python3 - "$inventory_limit" > "$probe_dir/choco-live-process-tree.log" 2>&1 <<'PY'
import sys
from pathlib import Path

limit = int(sys.argv[1])
processes = []
for path in Path("/proc").iterdir():
    if not path.name.isdigit():
        continue
    try:
        status = (path / "status").read_text(encoding="utf-8")
        fields = dict(
            line.split(":", 1) for line in status.splitlines() if ":" in line
        )
        command = (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        ).strip() or fields.get("Name", "").strip()
        processes.append((int(path.name), fields.get("PPid", "").strip(), fields.get("State", "").strip(), command))
    except (OSError, ValueError):
        continue
for pid, parent_pid, state, command in sorted(processes)[:limit]:
    print(f"{pid}\t{parent_pid}\t{state}\t{command}")
if len(processes) > limit:
    print(f"[truncated after {limit} processes]")
PY
  live_process_tree_rc="$?"
  wait "$live_probe_pid"
  live_probe_rc="$?"
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
  timeout "$inventory_timeout" python3 - "$inventory_limit" > "$probe_dir/process-tree.log" 2>&1 <<'PY'
import sys
from pathlib import Path

limit = int(sys.argv[1])
processes = []
for path in Path("/proc").iterdir():
    if not path.name.isdigit():
        continue
    try:
        status = (path / "status").read_text(encoding="utf-8")
        fields = dict(
            line.split(":", 1) for line in status.splitlines() if ":" in line
        )
        command = (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        ).strip() or fields.get("Name", "").strip()
        processes.append((int(path.name), fields.get("PPid", "").strip(), fields.get("State", "").strip(), command))
    except (OSError, ValueError):
        continue
for pid, parent_pid, state, command in sorted(processes)[:limit]:
    print(f"{pid}\t{parent_pid}\t{state}\t{command}")
if len(processes) > limit:
    print(f"[truncated after {limit} processes]")
PY
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
  python3 - "$diagnostic_json" "$failure_trigger" "$loader_rc" "$seh_rc" "$live_probe_rc" "$live_process_tree_rc" "$promoted_rc" "$registry_dump_rc" "$process_tree_rc" "$prefix_inventory_rc" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
trigger = sys.argv[2]
loader_rc, seh_rc, live_probe_rc, live_process_tree_rc, promoted_rc, registry_dump_rc, process_tree_rc, prefix_inventory_rc = sys.argv[3:]
payload = json.loads(path.read_text(encoding="utf-8"))
payload.setdefault("tiers", {})["failureOnly"] = {
    "status": "run",
    "failureTrigger": trigger,
    "checks": {
        "mscoreeLoaderAttempted": loader_rc in {"0", "1", "124"},
        "sehTraceAttempted": seh_rc in {"0", "1", "124"},
        "liveProbeAttempted": live_probe_rc in {"0", "1", "124"},
        "liveProcessTreeCaptured": live_process_tree_rc == "0",
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
