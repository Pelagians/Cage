set -eu
unset WINEDLLOVERRIDES
echo "[cage] Prepare pinned Chocolatey-for-wine release data"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
cfw_cache="$module_cache/chocolatey-for-wine/{{CHOCOLATEY_FOR_WINE_VERSION}}"
cfw_archive="$cfw_cache/Chocolatey-for-wine.7z"
cfw_extract="$cfw_cache/extracted/Chocolatey-for-wine"
cfw_archive_url="{{CHOCOLATEY_FOR_WINE_URL}}"
cfw_archive_sha256="{{CHOCOLATEY_FOR_WINE_SHA256}}"
cfw_winetricks_ps1="$cfw_cache/winetricks.ps1"
cfw_winetricks_url="{{WINETRICKS_PS1_URL}}"
cfw_winetricks_sha256="{{WINETRICKS_PS1_SHA256}}"
cfw_release_version='{{CHOCOLATEY_FOR_WINE_VERSION}}'
cfw_release_version="${cfw_release_version#v}"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
cfw_prefix_dir="$wine_prefix/drive_c/ProgramData/Chocolatey-for-wine"

extract_7z_archive() {
  archive="$1"
  dest="$2"
  mkdir -p "$dest"
  if command -v 7z >/dev/null 2>&1; then
    7z x -y "$archive" "-o$dest"
  elif command -v 7zz >/dev/null 2>&1; then
    7zz x -y "$archive" "-o$dest"
  elif command -v 7za >/dev/null 2>&1; then
    7za x -y "$archive" "-o$dest"
  else
    echo "[cage] ERROR: 7z/7zz/7za is required for Chocolatey-for-wine extraction" >&2
    exit 69
  fi
}

mkdir -p "$cfw_cache" "$cfw_prefix_dir"
echo "[cage] Resolving Chocolatey-for-wine {{CHOCOLATEY_FOR_WINE_VERSION}} from verified cache..."
cage_fetch_verified "$cfw_archive_url" "$cfw_archive_sha256" "$cfw_archive" "{{BOOTSTRAP_PROFILE_ID}}"
actual_cfw_archive_sha="$(sha256sum "$cfw_archive" | cut -d ' ' -f 1)"
test "$actual_cfw_archive_sha" = "$cfw_archive_sha256"
if [ ! -f "$cfw_extract/ChoCinstaller_${cfw_release_version}.exe" ]; then
  rm -rf "$cfw_cache/extracted"
  mkdir -p "$cfw_cache/extracted"
  extract_7z_archive "$cfw_archive" "$cfw_cache/extracted"
fi

test -f "$cfw_extract/ChoCinstaller_${cfw_release_version}.exe"
test -f "$cfw_extract/choc_install.ps1"
test -f "$cfw_extract/7z.exe"
test -f "$cfw_extract/7z.dll"
test -f "$cfw_extract/c_drive.7z"

echo "[cage] Resolving Chocolatey-for-wine winetricks.ps1 {{CHOCOLATEY_FOR_WINE_VERSION}} from verified cache..."
cage_fetch_verified "$cfw_winetricks_url" "$cfw_winetricks_sha256" "$cfw_winetricks_ps1" "{{BOOTSTRAP_PROFILE_ID}}"
test "$(sha256sum "$cfw_winetricks_ps1" | cut -d ' ' -f 1)" = "$cfw_winetricks_sha256"
cp -f "$cfw_winetricks_ps1" "$cfw_prefix_dir/winetricks.ps1"
echo "[cage] Pinned Chocolatey-for-wine release data prepared"
