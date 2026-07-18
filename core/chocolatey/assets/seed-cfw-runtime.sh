set -eu

echo "[cage] Seed verified CFW prepared prefix"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
runtime_cache="$module_cache/cfw-runtime/{{CFW_RUNTIME_PROFILE_KEY}}"
archive="$runtime_cache/cfw-runtime-prefix.tar.gz"
evidence="$runtime_cache/runtime.json"
manifest="$runtime_cache/cfw-runtime-manifest.json"
profile="$runtime_cache/runtime-profile.json"
helper="$runtime_cache/runtime-artifact.py"
profile_fields_file="$runtime_cache/profile-fields.txt"
manifest_fields_file="$runtime_cache/manifest-fields.txt"
metadata="$bundle_root/metadata/cfw-runtime.json"
manifest_metadata="$bundle_root/metadata/cfw-runtime-manifest.json"
CFW_RUNTIME_PROFILE_BASE64='{{CFW_RUNTIME_PROFILE_BASE64}}'
CFW_RUNTIME_HELPER_BASE64='{{CFW_RUNTIME_HELPER_BASE64}}'

mkdir -p "$runtime_cache" "$bundle_root/metadata"
printf '%s' "$CFW_RUNTIME_PROFILE_BASE64" | base64 -d > "$profile.part"
mv -f "$profile.part" "$profile"
printf '%s' "$CFW_RUNTIME_HELPER_BASE64" | base64 -d > "$helper.part"
mv -f "$helper.part" "$helper"

python3 "$helper" profile-fields "$profile" > "$profile_fields_file"
mapfile -t profile_fields < "$profile_fields_file"
if [ "${#profile_fields[@]}" -ne 7 ]; then
  echo "[cage] ERROR: invalid CFW runtime profile field count" >&2
  exit 64
fi
runtime_id="${profile_fields[0]}"
runtime_url="${profile_fields[1]}"
evidence_url="${profile_fields[2]}"
manifest_url="${profile_fields[3]}"
manifest_sha256="${profile_fields[4]}"
runtime_image="${profile_fields[5]}"
runtime_wine_versions="${profile_fields[6]}"

fetch_or_copy_verified() {
  source="$1"
  expected="$2"
  destination="$3"
  case "$source" in
    https://*)
      cage_fetch_verified "$source" "$expected" "$destination" "$runtime_id"
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

# The pinned manifest digest is the trust root. Archive and evidence digests are
# accepted only from that verified manifest, never from independent loose fields.
fetch_or_copy_verified "$manifest_url" "$manifest_sha256" "$manifest"
python3 "$helper" manifest-fields "$profile" "$manifest" > "$manifest_fields_file"
mapfile -t manifest_fields < "$manifest_fields_file"
if [ "${#manifest_fields[@]}" -ne 5 ]; then
  echo "[cage] ERROR: invalid CFW manifest field count" >&2
  exit 64
fi
archive_sha256="${manifest_fields[0]}"
evidence_sha256="${manifest_fields[1]}"
archive_bytes="${manifest_fields[2]}"
export CFW_CHOCOLATEY_WINDOWS_PATH="${manifest_fields[3]}"
cfw_chocolatey_prefix_relative="${manifest_fields[4]}"
export CFW_CHOCOLATEY_PREFIX_PATH="$WINEPREFIX/$cfw_chocolatey_prefix_relative"

fetch_or_copy_verified "$runtime_url" "$archive_sha256" "$archive"
fetch_or_copy_verified "$evidence_url" "$evidence_sha256" "$evidence"

# Verification includes schema/provenance/image/Wine checks and safe extraction
# into a temporary directory. The destination prefix is replaced only after all
# members and required runtime files pass validation.
python3 "$helper" verify-extract "$profile" "$manifest" "$evidence" "$archive" "$WINEPREFIX"

test -d "$WINEPREFIX/drive_c"
test -s "$CFW_CHOCOLATEY_PREFIX_PATH"

cp -f "$evidence" "$metadata.part"
mv -f "$metadata.part" "$metadata"
cp -f "$manifest" "$manifest_metadata.part"
mv -f "$manifest_metadata.part" "$manifest_metadata"
if [ -L "$WINEPREFIX/.cfw" ]; then
  echo "[cage] ERROR: prepared prefix .cfw metadata path must not be a symlink" >&2
  exit 66
fi
mkdir -p "$WINEPREFIX/.cfw"
cp -f "$evidence" "$WINEPREFIX/.cfw/runtime.json.part"
mv -f "$WINEPREFIX/.cfw/runtime.json.part" "$WINEPREFIX/.cfw/runtime.json"
cp -f "$manifest" "$WINEPREFIX/.cfw/manifest.json.part"
mv -f "$WINEPREFIX/.cfw/manifest.json.part" "$WINEPREFIX/.cfw/manifest.json"
touch "$WINEPREFIX/.cage-prefix-seeded"

echo "[cage] CFW prepared prefix seeded"
