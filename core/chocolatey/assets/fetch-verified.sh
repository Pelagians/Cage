# Shared content-addressed download helper for Chocolatey bootstrap assets.
cage_fetch_verified() {
  url="$1"
  sha256="$2"
  destination="$3"
  profile_id="$4"
  if [ "${#sha256}" -ne 64 ]; then
    echo "[cage] ERROR: incomplete bootstrap sha256 for $url" >&2
    return 64
  fi
  case "$sha256" in
    *[!0-9a-f]*) echo "[cage] ERROR: invalid bootstrap sha256 for $url" >&2; return 64 ;;
  esac
  module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
  blob_dir="$module_cache/blobs/sha256"
  profile_dir="$module_cache/profiles"
  blob="$blob_dir/$sha256"
  lock="$blob.lock"
  mkdir -p "$blob_dir" "$profile_dir" "$(dirname "$destination")"
  exec 9>"$lock"
  flock 9
  if [ -f "$blob" ] && [ "$(sha256sum "$blob" | cut -d ' ' -f 1)" != "$sha256" ]; then
    echo "[cage] Removing corrupt cached blob: $blob" >&2
    rm -f "$blob"
  fi
  if [ ! -f "$blob" ]; then
    part="$blob.part.$$"
    rm -f "$part"
    if ! curl --fail --location --retry 3 --connect-timeout "${CAGE_CACHE_CONNECT_TIMEOUT:-30}" --max-time "${CAGE_CACHE_TOTAL_TIMEOUT:-1800}" --output "$part" "$url"; then
      rm -f "$part"
      return 65
    fi
    actual="$(sha256sum "$part" | cut -d ' ' -f 1)"
    if [ "$actual" != "$sha256" ]; then
      echo "[cage] ERROR: downloaded bootstrap checksum mismatch for $url" >&2
      rm -f "$part"
      return 66
    fi
    mv "$part" "$blob"
  fi
  cp -f "$blob" "$destination"
  destination_actual="$(sha256sum "$destination" | cut -d ' ' -f 1)"
  if [ "$destination_actual" != "$sha256" ]; then
    echo "[cage] ERROR: bootstrap destination checksum mismatch: $destination" >&2
    rm -f "$destination"
    return 67
  fi
  profile_lock="$profile_dir/$profile_id.lock"
  exec 8>"$profile_lock"
  flock 8
  python3 - "$profile_dir/$profile_id.json" "$profile_id" "$url" "$sha256" <<'PY'
import json
import sys
from pathlib import Path
path, profile_id, url, sha256 = sys.argv[1:]
target = Path(path)
payload = {"profile": profile_id, "assets": {}}
if target.exists():
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
payload.setdefault("assets", {})[sha256] = {"url": url, "sha256": sha256}
temporary = target.with_suffix(target.suffix + ".part")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(target)
PY
  flock -u 8
  flock -u 9
}
