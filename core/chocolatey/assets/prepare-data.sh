set -eu
unset WINEDLLOVERRIDES
echo "[cage] Prepare Chocolatey-for-wine data"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
cfw_cache="$module_cache/chocolatey-for-wine/{{CHOCOLATEY_FOR_WINE_VERSION}}"
cfw_archive="$cfw_cache/Chocolatey-for-wine.7z"
cfw_extract="$cfw_cache/extracted/Chocolatey-for-wine"
cfw_archive_url="{{CHOCOLATEY_FOR_WINE_URL}}"
cfw_archive_sha256="{{CHOCOLATEY_FOR_WINE_SHA256}}"
cfw_winetricks_ps1="$cfw_cache/winetricks.ps1"
cfw_winetricks_url="{{WINETRICKS_PS1_URL}}"
cfw_winetricks_sha256="{{WINETRICKS_PS1_SHA256}}"
cfw_c_drive_extract="$cfw_cache/c_drive-extracted"
choco_cache="$module_cache/chocolatey/{{CHOCOLATEY_VERSION}}"
choco_nupkg="$choco_cache/chocolatey.{{CHOCOLATEY_VERSION}}.nupkg"
choco_nupkg_url="{{CHOCOLATEY_NUPKG_URL}}"
choco_nupkg_sha256="{{CHOCOLATEY_NUPKG_SHA256}}"
program_data="$wine_prefix/drive_c/ProgramData"
cfw_prefix_dir="$program_data/Chocolatey-for-wine"
tools_root="$program_data/tools"
raw_choco_dir="$tools_root/ChocolateyInstall"
raw_choco_exe="${WINEPREFIX:-$HOME/.wine}/drive_c/ProgramData/tools/ChocolateyInstall/choco.exe"

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
    python3 - "$archive" "$dest" <<'PY'
import sys
import py7zr
archive, dest = sys.argv[1], sys.argv[2]
with py7zr.SevenZipFile(archive, mode="r") as zf:
    zf.extractall(dest)
PY
  fi
}

mkdir -p "$cfw_cache" "$choco_cache" "$program_data" "$tools_root" "$cfw_prefix_dir"
echo "[cage] Resolving Chocolatey-for-wine data {{CHOCOLATEY_FOR_WINE_VERSION}} from verified cache..."
cage_fetch_verified "$cfw_archive_url" "$cfw_archive_sha256" "$cfw_archive" "{{BOOTSTRAP_PROFILE_ID}}"
actual_cfw_archive_sha="$(sha256sum "$cfw_archive" | cut -d ' ' -f 1)"
if [ "$actual_cfw_archive_sha" != "$cfw_archive_sha256" ]; then
  echo "[cage] ERROR: Chocolatey-for-wine archive checksum mismatch"
  exit 1
fi
if [ ! -f "$cfw_extract/choc_install.ps1" ] || [ ! -f "$cfw_extract/7z.exe" ] || [ ! -f "$cfw_extract/c_drive.7z" ]; then
  rm -rf "$cfw_cache/extracted"
  mkdir -p "$cfw_cache/extracted"
  echo "[cage] Extracting Chocolatey-for-wine release data..."
  extract_7z_archive "$cfw_archive" "$cfw_cache/extracted"
fi

test -f "$cfw_extract/choc_install.ps1"
test -f "$cfw_extract/7z.exe"
test -f "$cfw_extract/7z.dll"
test -f "$cfw_extract/c_drive.7z"

echo "[cage] Resolving Chocolatey-for-wine winetricks.ps1 {{CHOCOLATEY_FOR_WINE_VERSION}} from verified cache..."
cage_fetch_verified "$cfw_winetricks_url" "$cfw_winetricks_sha256" "$cfw_winetricks_ps1" "{{BOOTSTRAP_PROFILE_ID}}"
actual_cfw_winetricks_sha="$(sha256sum "$cfw_winetricks_ps1" | cut -d ' ' -f 1)"
if [ "$actual_cfw_winetricks_sha" != "$cfw_winetricks_sha256" ]; then
  echo "[cage] ERROR: Chocolatey-for-wine winetricks.ps1 checksum mismatch"
  exit 1
fi

test -f "$cfw_winetricks_ps1"

echo "[cage] Resolving Chocolatey {{CHOCOLATEY_VERSION}} nupkg from verified cache..."
cage_fetch_verified "$choco_nupkg_url" "$choco_nupkg_sha256" "$choco_nupkg" "{{BOOTSTRAP_PROFILE_ID}}"
actual_choco_nupkg_sha="$(sha256sum "$choco_nupkg" | cut -d ' ' -f 1)"
if [ "$actual_choco_nupkg_sha" != "$choco_nupkg_sha256" ]; then
  echo "[cage] ERROR: Chocolatey nupkg checksum mismatch"
  echo "[cage]   expected: $choco_nupkg_sha256"
  echo "[cage]   actual:   $actual_choco_nupkg_sha"
  exit 1
fi

echo "[cage] Extracting Chocolatey-for-wine c_drive.7z data..."
rm -rf "$cfw_c_drive_extract"
mkdir -p "$cfw_c_drive_extract" "$wine_prefix/drive_c"
extract_7z_archive "$cfw_extract/c_drive.7z" "$cfw_c_drive_extract"
python3 - "$cfw_c_drive_extract" "$wine_prefix/drive_c" <<'PY'
import shutil
import sys
from pathlib import Path

extract_root = Path(sys.argv[1])
drive_c = Path(sys.argv[2])

# PietJankbal's c_drive.7z preserves a Windows drive root as "c:". 7z on
# Linux treats that as a literal directory name, so extracting straight into
# the Wine drive creates drive_c/c:/ProgramData/... instead of
# drive_c/ProgramData/....  Flatten that root explicitly before continuing.
source_root = extract_root / "c:"
if not source_root.exists():
    source_root = extract_root

for item in source_root.iterdir():
    target = drive_c / item.name
    if item.is_dir():
        shutil.copytree(item, target, dirs_exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)

bad_nested_root = drive_c / "c:"
if bad_nested_root.exists():
    shutil.rmtree(bad_nested_root)
PY
if [ -d "$wine_prefix/drive_c/c:" ]; then
  echo "[cage] ERROR: Chocolatey-for-wine c_drive.7z extracted nested c: root into Wine drive_c"
  exit 66
fi

rm -rf "$raw_choco_dir"
mkdir -p "$raw_choco_dir" "$cfw_prefix_dir"
python3 - "$choco_nupkg" "$tools_root" <<'PY'
import sys
import zipfile
from pathlib import Path
archive = Path(sys.argv[1])
tools_root = Path(sys.argv[2])
prefix = "tools/chocolateyInstall/"
with zipfile.ZipFile(archive) as zf:
    for member in zf.infolist():
        name = member.filename.replace("\\", "/")
        if not name.startswith(prefix) or name.endswith("/"):
            continue
        target = tools_root / "ChocolateyInstall" / name[len(prefix):]
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, target.open("wb") as dst:
            dst.write(src.read())
PY

test -f "$raw_choco_exe"
cp -f "$cfw_extract/choc_install.ps1" "$cfw_prefix_dir/choc_install.ps1"
cp -f "$cfw_winetricks_ps1" "$cfw_prefix_dir/winetricks.ps1"
cp -f "$cfw_extract/7z.exe" "$cfw_prefix_dir/7z.exe"
cp -f "$cfw_extract/7z.dll" "$cfw_prefix_dir/7z.dll"
echo "[cage] Prepared Chocolatey-for-wine data and Chocolatey nupkg"
