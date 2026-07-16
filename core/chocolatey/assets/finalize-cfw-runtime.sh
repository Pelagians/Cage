set -eu
unset WINEDLLOVERRIDES

echo "[cage] Finalize CFW integrated Chocolatey runtime"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
runtime_cache="$module_cache/cfw-runtime/{{BOOTSTRAP_PROFILE_ID}}"
payload_cache="$runtime_cache/payloads"
runtime_script="$runtime_cache/container-runtime.sh"

mkdir -p "$payload_cache" "$bundle_root/cfw-runtime"

cage_fetch_verified \
  "{{CFW_CONTAINER_RUNTIME_URL}}" \
  "{{CFW_CONTAINER_RUNTIME_SHA256}}" \
  "$runtime_script" \
  "{{BOOTSTRAP_PROFILE_ID}}"

cage_fetch_verified \
  "{{WINDOWS_POWERSHELL_URL}}" \
  "{{WINDOWS_POWERSHELL_SHA256}}" \
  "$payload_cache/windowsserver2003-kb968930-x64-eng_8ba702aa016e4c5aed581814647f4d55635eff5c.exe" \
  "{{BOOTSTRAP_PROFILE_ID}}"

cage_fetch_verified \
  "{{MSCOREE_UPDATE_URL}}" \
  "{{MSCOREE_UPDATE_SHA256}}" \
  "$payload_cache/windows6.1-kb958488-v6001-x64_a137e4f328f01146dfa75d7b5a576090dee948dc.msu" \
  "{{BOOTSTRAP_PROFILE_ID}}"

export CFW_PAYLOAD_CACHE_POSIX="$payload_cache"
export CFW_EVIDENCE_ROOT="$bundle_root/cfw-runtime"
export CFW_MSCOREE_TIMEOUT="${CAGE_CFW_MSCOREE_TIMEOUT:-600s}"
export CFW_CHOCO_TIMEOUT="${CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-180s}"

sh "$runtime_script"

test -s "$bundle_root/cfw-runtime/container-runtime.json"
python3 - "$bundle_root/cfw-runtime/container-runtime.json" <<'PY'
import json
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if record.get("status") != "passed":
    raise SystemExit("CFW integrated runtime evidence did not pass")
if record.get("provider") != "cfw-integrated-chocolatey-runtime":
    raise SystemExit("unexpected CFW runtime provider")
PY

echo "[cage] CFW integrated Chocolatey runtime verified"
