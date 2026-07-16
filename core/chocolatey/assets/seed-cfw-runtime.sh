set -eu

echo "[cage] Seed verified CFW prepared prefix"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
runtime_cache="$module_cache/cfw-runtime/{{CFW_RUNTIME_ID}}"
archive="$runtime_cache/cfw-runtime-prefix.tar.gz"
evidence="$runtime_cache/runtime.json"
metadata="$bundle_root/metadata/cfw-runtime.json"

mkdir -p "$runtime_cache" "$bundle_root/metadata"

fetch_or_copy_verified() {
  source="$1"
  expected="$2"
  destination="$3"
  case "$source" in
    https://*)
      cage_fetch_verified "$source" "$expected" "$destination" "{{CFW_RUNTIME_ID}}"
      ;;
    file://*)
      local_path="${source#file://}"
      cp -f "$local_path" "$destination"
      ;;
    /*)
      cp -f "$source" "$destination"
      ;;
    *)
      echo "[cage] ERROR: CFW runtime source must be https://, file://, or absolute" >&2
      exit 64
      ;;
  esac
  actual="$(sha256sum "$destination" | cut -d ' ' -f 1)"
  if [ "$actual" != "$expected" ]; then
    echo "[cage] ERROR: CFW runtime checksum mismatch: $destination" >&2
    echo "[cage] expected=$expected actual=$actual" >&2
    exit 66
  fi
}

fetch_or_copy_verified "{{CFW_RUNTIME_URL}}" "{{CFW_RUNTIME_SHA256}}" "$archive"
fetch_or_copy_verified "{{CFW_RUNTIME_EVIDENCE_URL}}" "{{CFW_RUNTIME_EVIDENCE_SHA256}}" "$evidence"

python3 - "$evidence" "{{CFW_RUNTIME_ID}}" "{{CFW_RUNTIME_WINE_VERSIONS}}" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_id = sys.argv[2]
allowed = {value for value in sys.argv[3].split(",") if value}
record = json.loads(path.read_text(encoding="utf-8"))
if record.get("status") != "passed":
    raise SystemExit("CFW runtime evidence status is not passed")
if record.get("provider") != "cfw-chocolatey-runtime":
    raise SystemExit("unexpected CFW runtime provider")
if record.get("runtimeId") not in {None, expected_id}:
    raise SystemExit("CFW runtime evidence identity mismatch")
current = subprocess.run(["wine", "--version"], text=True, capture_output=True, check=True).stdout.strip()
if allowed and not any(version in current for version in allowed):
    raise SystemExit(f"CFW runtime does not declare compatibility with {current}")
required = {"installer", "pwsh", "chocolatey", "synchroX64", "synchroX86", "finalSettle"}
checks = record.get("checks", {})
missing = sorted(name for name in required if checks.get(name) is not True)
if missing:
    raise SystemExit("CFW runtime evidence is missing required proofs: " + ", ".join(missing))
PY

rm -rf "$WINEPREFIX"
mkdir -p "$WINEPREFIX"
tar -xzf "$archive" -C "$WINEPREFIX"
test -d "$WINEPREFIX/drive_c"
test -s "$WINEPREFIX/drive_c/ProgramData/chocolatey/bin/choco.exe"
test -s "$WINEPREFIX/drive_c/windows/system32/WindowsPowerShell/v1.0/powershell.exe"
test -s "$WINEPREFIX/drive_c/windows/syswow64/WindowsPowerShell/v1.0/powershell.exe"

cp -f "$evidence" "$metadata.part"
mv -f "$metadata.part" "$metadata"
mkdir -p "$WINEPREFIX/.cfw"
cp -f "$evidence" "$WINEPREFIX/.cfw/runtime.json.part"
mv -f "$WINEPREFIX/.cfw/runtime.json.part" "$WINEPREFIX/.cfw/runtime.json"
touch "$WINEPREFIX/.cage-prefix-seeded"

echo "[cage] CFW prepared prefix seeded"
