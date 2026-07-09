"""Deterministic Chocolatey package manager module for Wine environments.

Chocolatey-for-wine is consumed as pinned release data. Cage never executes the
upstream ChoCinstaller bootstrapper; instead it performs each prerequisite as a
separate, named, verifiable build step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

DEFAULT_CHOCOLATEY_FOR_WINE_VERSION = "v0.5c.755"
DEFAULT_CHOCOLATEY_FOR_WINE_SHA256 = "87f4ecc08a9b22f16aa5633ca107c151ddf3fed0b256fed9fb99680af7095d14"
DEFAULT_CHOCOLATEY_VERSION = "2.6.0"
DEFAULT_CHOCOLATEY_NUPKG_SHA256 = "f13a2af9cd4ec2c9b58d81861bc95ad7151e3a871d8f758dffa72a996a3792d8"
DEFAULT_CFW_WINETRICKS_SHA256 = "1d74ffad96f2052d42a0fa3c7ac5dbc8d099e7ad9f9aba3213446a25b34ff48c"
DEFAULT_DOTNET48_SHA256 = "0a3a390c47e639d0f7fc65b21195fee6b7f65b066f80f70c60fab191d14b7e40"
DEFAULT_POWERSHELL_MSI_VERSION = "7.5.5"
DEFAULT_POWERSHELL_MSI_NAME = f"PowerShell-{DEFAULT_POWERSHELL_MSI_VERSION}-win-x64.msi"
DEFAULT_POWERSHELL_MSI_SHA256 = "b2ac56b7639e2b259bb78bab077555d76f2a5eec6c516690d63de36bc1d6ca25"
POWERSHELL_MSI_PRODUCT_CODE = "634F4903-28DC-4BA6-A39F-4B3E394D4E36"


def _sh_single_quote(value: str) -> str:
    """Quote a value for POSIX shell single-quoted context."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


@dataclass
class ChocolateyModule(ModuleBase):
    """Install Chocolatey packages through deterministic Wine build steps."""

    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None
    version: str = DEFAULT_CHOCOLATEY_FOR_WINE_VERSION
    sha256: str | None = None

    def capabilities(self) -> dict[str, str]:
        """Return PowerShell-related capability slots claimed by Chocolatey."""
        return {
            "engine": "chocolatey-powershell-msi",
            "winps-shim": "chocolatey-native",
            "shim-library": "chocolatey-for-wine",
        }

    def build(self) -> list[BuildStep]:
        """Generate deterministic Chocolatey setup and package install steps."""
        if not self.install:
            raise ModuleError("chocolatey module requires 'install' field")

        if not isinstance(self.install, dict):
            raise ModuleError("chocolatey module 'install' must be an object")

        packages = self.install.get("packages", [])
        if not packages:
            raise ModuleError("chocolatey module 'install.packages' cannot be empty")
        if not isinstance(packages, list) or not all(isinstance(pkg, str) and pkg for pkg in packages):
            raise ModuleError("chocolatey module 'install.packages' must be a list of non-empty strings")

        package_pattern = re.compile(r"^[a-zA-Z0-9._+\-]+$")
        for pkg in packages:
            if not package_pattern.match(pkg):
                raise ModuleError(
                    "chocolatey package names must use letters, numbers, dots, underscores, plus, or dashes only: "
                    f"{pkg}"
                )

        if self.source and not self.source.startswith(("http://", "https://")):
            raise ModuleError(f"Invalid chocolatey source URL: {self.source}")

        wine_prefix = "${WINEPREFIX:-$HOME/.wine}"
        choco_exe = f"{wine_prefix}/drive_c/ProgramData/chocolatey/bin/choco.exe"
        raw_choco_exe = f"{wine_prefix}/drive_c/ProgramData/tools/ChocolateyInstall/choco.exe"
        package_args = " ".join(packages)
        source_arg = f" -s {_sh_single_quote(self.source)}" if self.source else ""

        return [
            self._powershell_msi_step(wine_prefix),
            self._prepare_chocolatey_data_step(wine_prefix, raw_choco_exe),
            self._dotnet48_step(wine_prefix),
            self._registry_prep_step(),
            self._finalize_step(wine_prefix, choco_exe, raw_choco_exe),
            self._diagnostic_step(wine_prefix, choco_exe, raw_choco_exe),
            self._package_install_step(choco_exe, package_args, source_arg),
        ]

    def _powershell_msi_step(self, wine_prefix: str) -> BuildStep:
        pwsh_msi_url = (
            "https://github.com/PowerShell/PowerShell/releases/download/"
            f"v{DEFAULT_POWERSHELL_MSI_VERSION}/{DEFAULT_POWERSHELL_MSI_NAME}"
        )
        script = f'''set -eu
unset WINEDLLOVERRIDES
echo "[cage] Install PowerShell {DEFAULT_POWERSHELL_MSI_VERSION} MSI for Chocolatey"
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
pwsh_cache="$module_cache/powershell-msi/{DEFAULT_POWERSHELL_MSI_VERSION}"
pwsh_msi="$pwsh_cache/{DEFAULT_POWERSHELL_MSI_NAME}"
pwsh_msi_url="{pwsh_msi_url}"
pwsh_msi_sha256="{DEFAULT_POWERSHELL_MSI_SHA256}"
pwsh_exe="$wine_prefix/drive_c/Program Files/PowerShell/7/pwsh.exe"
pwsh_product_key='HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{{{POWERSHELL_MSI_PRODUCT_CODE}}}'
mkdir -p "$pwsh_cache"
if [ ! -f "$pwsh_msi" ]; then
  echo "[cage] Downloading PowerShell {DEFAULT_POWERSHELL_MSI_VERSION} MSI..."
  curl -fL --retry 3 -o "$pwsh_msi" "$pwsh_msi_url"
fi
actual_pwsh_msi_sha="$(sha256sum "$pwsh_msi" | cut -d ' ' -f 1)"
if [ "$actual_pwsh_msi_sha" != "$pwsh_msi_sha256" ]; then
  echo "[cage] ERROR: PowerShell MSI checksum mismatch"
  echo "[cage]   expected: $pwsh_msi_sha256"
  echo "[cage]   actual:   $actual_pwsh_msi_sha"
  exit 1
fi
pwsh_msi_win="$(winepath -w "$pwsh_msi")"
pwsh_msiexec_log="$pwsh_cache/powershell-msiexec.log"
pwsh_msiexec_log_win="$(winepath -w "$pwsh_msiexec_log")"
rm -f "$pwsh_msiexec_log"
echo "[cage] Installing PowerShell {DEFAULT_POWERSHELL_MSI_VERSION} through dedicated MSI step..."
echo "[cage] PowerShell MSI: $pwsh_msi_win"
set +e
timeout "${{CAGE_POWERSHELL_MSI_TIMEOUT:-1200s}}" wine msiexec /i "$pwsh_msi_win" ADD_EXPLORER_CONTEXT_MENU_OPENPOWERSHELL=0 ENABLE_PSREMOTING=0 REGISTER_MANIFEST=1 USE_MU=0 ENABLE_MU=0 /QN /NORESTART /L*v "$pwsh_msiexec_log_win"
pwsh_msi_rc="$?"
set -e
if [ -f "$pwsh_msiexec_log" ]; then
  echo "[cage] PowerShell MSI failure markers:"
  grep -nEi 'Return value 3|MainEngineThread|Error [0-9]+|Fatal error' "$pwsh_msiexec_log" | head -80 | sed 's/^/[powershell-msi-marker] /' || true
  echo "[cage] PowerShell MSI log tail:"
  tail -120 "$pwsh_msiexec_log" | sed 's/^/[powershell-msi] /'
fi
if [ "$pwsh_msi_rc" -ne 0 ]; then
  echo "[cage] PowerShell MSI Wine exit code: $pwsh_msi_rc"
fi
if [ ! -f "$pwsh_exe" ]; then
  echo "[cage] ERROR: PowerShell MSI did not install pwsh.exe: $pwsh_exe"
  exit 68
fi
test -f "$pwsh_exe"
chmod +x "$pwsh_exe"
set +e
timeout "${{CAGE_WINE_REG_TIMEOUT:-120s}}" wine reg query "$pwsh_product_key" >/dev/null 2>&1
pwsh_product_rc="$?"
set -e
if [ "$pwsh_product_rc" -ne 0 ]; then
  echo "[cage] WARNING: PowerShell MSI product registry key not found: $pwsh_product_key"
else
  echo "[cage] PowerShell MSI product registry key present"
fi
echo "[cage] PowerShell MSI installed: $pwsh_exe"'''
        return BuildStep(commands=[script], description="Install PowerShell 7 MSI for Chocolatey", kind="wine-msiexec", timeout=1200)

    def _prepare_chocolatey_data_step(self, wine_prefix: str, raw_choco_exe: str) -> BuildStep:
        release_url = (
            "https://github.com/PietJankbal/Chocolatey-for-wine/releases/download/"
            f"{self.version}/Chocolatey-for-wine.7z"
        )
        expected_cfw_sha = self.sha256
        if expected_cfw_sha is None and self.version == DEFAULT_CHOCOLATEY_FOR_WINE_VERSION:
            expected_cfw_sha = DEFAULT_CHOCOLATEY_FOR_WINE_SHA256
        expected_cfw_sha = expected_cfw_sha or ""
        choco_nupkg_url = f"https://community.chocolatey.org/api/v2/package/chocolatey/{DEFAULT_CHOCOLATEY_VERSION}"

        script = f'''set -eu
unset WINEDLLOVERRIDES
echo "[cage] Prepare Chocolatey-for-wine data"
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
cfw_cache="$module_cache/chocolatey-for-wine/{self.version}"
cfw_archive="$cfw_cache/Chocolatey-for-wine.7z"
cfw_extract="$cfw_cache/extracted/Chocolatey-for-wine"
cfw_archive_url="{release_url}"
cfw_archive_sha256="{expected_cfw_sha}"
cfw_winetricks_ps1="$cfw_cache/winetricks.ps1"
cfw_winetricks_url="https://raw.githubusercontent.com/PietJankbal/Chocolatey-for-wine/{self.version}/winetricks.ps1"
cfw_winetricks_sha256="{DEFAULT_CFW_WINETRICKS_SHA256 if self.version == DEFAULT_CHOCOLATEY_FOR_WINE_VERSION else ''}"
cfw_c_drive_extract="$cfw_cache/c_drive-extracted"
choco_cache="$module_cache/chocolatey/{DEFAULT_CHOCOLATEY_VERSION}"
choco_nupkg="$choco_cache/chocolatey.{DEFAULT_CHOCOLATEY_VERSION}.nupkg"
choco_nupkg_url="{choco_nupkg_url}"
choco_nupkg_sha256="{DEFAULT_CHOCOLATEY_NUPKG_SHA256}"
program_data="$wine_prefix/drive_c/ProgramData"
cfw_prefix_dir="$program_data/Chocolatey-for-wine"
tools_root="$program_data/tools"
raw_choco_dir="$tools_root/ChocolateyInstall"
raw_choco_exe="{raw_choco_exe}"

extract_7z_archive() {{
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
}}

mkdir -p "$cfw_cache" "$choco_cache" "$program_data" "$tools_root" "$cfw_prefix_dir"
if [ ! -f "$cfw_archive" ]; then
  echo "[cage] Downloading Chocolatey-for-wine data {self.version}..."
  curl -fL --retry 3 -o "$cfw_archive" "$cfw_archive_url"
fi
if [ -n "$cfw_archive_sha256" ]; then
  actual_cfw_archive_sha="$(sha256sum "$cfw_archive" | cut -d ' ' -f 1)"
  if [ "$actual_cfw_archive_sha" != "$cfw_archive_sha256" ]; then
    echo "[cage] ERROR: Chocolatey-for-wine archive checksum mismatch"
    echo "[cage]   expected: $cfw_archive_sha256"
    echo "[cage]   actual:   $actual_cfw_archive_sha"
    exit 1
  fi
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

if [ ! -f "$cfw_winetricks_ps1" ]; then
  echo "[cage] Downloading Chocolatey-for-wine winetricks.ps1 {self.version}..."
  curl -fL --retry 3 -o "$cfw_winetricks_ps1" "$cfw_winetricks_url"
fi
if [ -n "$cfw_winetricks_sha256" ]; then
  actual_cfw_winetricks_sha="$(sha256sum "$cfw_winetricks_ps1" | cut -d ' ' -f 1)"
  if [ "$actual_cfw_winetricks_sha" != "$cfw_winetricks_sha256" ]; then
    echo "[cage] ERROR: Chocolatey-for-wine winetricks.ps1 checksum mismatch"
    echo "[cage]   expected: $cfw_winetricks_sha256"
    echo "[cage]   actual:   $actual_cfw_winetricks_sha"
    exit 1
  fi
fi

test -f "$cfw_winetricks_ps1"

if [ ! -f "$choco_nupkg" ]; then
  echo "[cage] Downloading Chocolatey {DEFAULT_CHOCOLATEY_VERSION} nupkg..."
  curl -fL --retry 3 -o "$choco_nupkg" "$choco_nupkg_url"
fi
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
        name = member.filename.replace("\\\\", "/")
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
echo "[cage] Prepared Chocolatey-for-wine data and Chocolatey nupkg"'''
        return BuildStep(commands=[script], description="Prepare Chocolatey-for-wine data", kind="extract")

    def _dotnet48_step(self, wine_prefix: str) -> BuildStep:
        script = f'''set -eu
unset WINEDLLOVERRIDES
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
dotnet_cache="$module_cache/dotnet48"
ndp48_exe="$dotnet_cache/NDP48-x86-x64-AllOS-ENU.exe"
ndp48_url="https://go.microsoft.com/fwlink/?linkid=2088631"
ndp48_sha256="{DEFAULT_DOTNET48_SHA256}"
setupcache="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/SetupCache"
dotnet_extract="$setupcache/v4.8.03761"
netfx_msi_x86="$dotnet_extract/netfx_Full_x86.msi"
netfx_msi_x64="$dotnet_extract/netfx_Full_x64.msi"
mkdir -p "$dotnet_cache" "$setupcache"
if [ ! -f "$ndp48_exe" ]; then
  echo "[cage] Downloading .NET Framework 4.8 offline installer..."
  curl -fL --retry 3 -o "$ndp48_exe" "$ndp48_url"
fi
actual_ndp48_sha="$(sha256sum "$ndp48_exe" | cut -d ' ' -f 1)"
if [ "$actual_ndp48_sha" != "$ndp48_sha256" ]; then
  echo "[cage] ERROR: .NET Framework 4.8 installer checksum mismatch"
  echo "[cage]   expected: $ndp48_sha256"
  echo "[cage]   actual:   $actual_ndp48_sha"
  exit 1
fi
if [ ! -f "$netfx_msi_x86" ] || [ ! -f "$netfx_msi_x64" ]; then
  rm -rf "$dotnet_extract"
  mkdir -p "$dotnet_extract"
  echo "[cage] Extracting .NET Framework 4.8 payload to Wine SetupCache..."
  if command -v 7z >/dev/null 2>&1; then
    7z x -y -x!"*.cab" -x!"netfx_c*" -x!"netfx_e*" -x!"NetFx4*" -ms190M "$ndp48_exe" "-o$dotnet_extract"
  elif command -v 7zz >/dev/null 2>&1; then
    7zz x -y -x!"*.cab" -x!"netfx_c*" -x!"netfx_e*" -x!"NetFx4*" -ms190M "$ndp48_exe" "-o$dotnet_extract"
  elif command -v 7za >/dev/null 2>&1; then
    7za x -y -x!"*.cab" -x!"netfx_c*" -x!"netfx_e*" -x!"NetFx4*" -ms190M "$ndp48_exe" "-o$dotnet_extract"
  else
    echo "[cage] ERROR: 7z/7zz/7za is required to extract the .NET Framework 4.8 payload"
    exit 1
  fi
fi
test -f "$netfx_msi_x86"
test -f "$netfx_msi_x64"
dotnet_mscoree_marker_x86="$wine_prefix/drive_c/windows/syswow64/mscoree.dll"
dotnet_clr_marker_x86="$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/clr.dll"
dotnet_mscoree_marker_x64="$wine_prefix/drive_c/windows/system32/mscoree.dll"
dotnet_clr_marker_x64="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"

install_dotnet_msi() {{
  label="$1"
  netfx_msi="$2"
  dotnet_mscoree_marker="$3"
  dotnet_clr_marker="$4"
  if [ -f "$dotnet_mscoree_marker" ] && [ -f "$dotnet_clr_marker" ]; then
    echo "[cage] .NET Framework 4.8 $label already has native CLR markers; skipping MSI install"
    echo "[cage] .NET Framework 4.8 $label native mscoree exists: $dotnet_mscoree_marker"
    echo "[cage] .NET Framework 4.8 $label native CLR exists: $dotnet_clr_marker"
    return 0
  fi
  netfx_msi_win="$(winepath -w "$netfx_msi")"
  dotnet_msiexec_log="$dotnet_cache/dotnet48-$label-msiexec.log"
  dotnet_msiexec_log_win="$(winepath -w "$dotnet_msiexec_log")"
  rm -f "$dotnet_msiexec_log"
  echo "[cage] Installing .NET Framework 4.8 $label MSI from dedicated MSI step..."
  echo "[cage] .NET Framework 4.8 $label MSI: $netfx_msi_win"
  set +e
  timeout "${{CAGE_DOTNET48_TIMEOUT:-1800s}}" wine msiexec /i "$netfx_msi_win" MSIFASTINSTALL=2 DISABLEROLLBACK=1 /QN /NORESTART /L*v "$dotnet_msiexec_log_win"
  dotnet_msi_rc="$?"
  set -e
  if [ -f "$dotnet_msiexec_log" ]; then
    echo "[cage] .NET Framework 4.8 $label MSI failure markers:"
    grep -nEi 'NEWERVERSIONDETECTED|CA_BlockOlderVersionInstall|Return value 0|Return value 3|MainEngineThread|Error [0-9]+|Fatal error' "$dotnet_msiexec_log" | head -80 | sed "s/^/[dotnet48-$label-msi-marker] /" || true
    echo "[cage] .NET Framework 4.8 $label MSI log tail:"
    tail -120 "$dotnet_msiexec_log" | sed "s/^/[dotnet48-$label-msi] /"
  fi
  dotnet_msi_success=0
  if [ -f "$dotnet_msiexec_log" ] && grep -qE 'Action ended .*INSTALL[.] Return value 1' "$dotnet_msiexec_log"; then
    dotnet_msi_success=1
  fi
  dotnet_marker_success=0
  if [ -f "$dotnet_mscoree_marker" ] && [ -f "$dotnet_clr_marker" ]; then
    dotnet_marker_success=1
  fi
  if [ "$dotnet_msi_success" -ne 1 ] && [ "$dotnet_marker_success" -ne 1 ]; then
    echo "[cage] ERROR: .NET Framework 4.8 $label MSI did not report INSTALL success and required native CLR markers are absent"
    if [ "$dotnet_msi_rc" -ne 0 ]; then
      echo "[cage] ERROR: Wine msiexec exit code for .NET $label: $dotnet_msi_rc"
      exit "$dotnet_msi_rc"
    fi
    exit 67
  fi
  if [ "$dotnet_msi_success" -ne 1 ]; then
    echo "[cage] .NET Framework 4.8 $label MSI did not report INSTALL success, but required native CLR markers exist; continuing"
  elif [ "$dotnet_msi_rc" -ne 0 ]; then
    echo "[cage] .NET Framework 4.8 $label MSI log reports INSTALL success; ignoring Wine msiexec exit $dotnet_msi_rc"
  fi
  if [ ! -f "$dotnet_mscoree_marker" ]; then
    echo "[cage] ERROR: .NET Framework 4.8 $label MSI did not create native mscoree: $dotnet_mscoree_marker"
    exit 67
  fi
  if [ ! -f "$dotnet_clr_marker" ]; then
    echo "[cage] ERROR: .NET Framework 4.8 $label MSI did not create native CLR: $dotnet_clr_marker"
    exit 67
  fi
  echo "[cage] .NET Framework 4.8 $label native mscoree exists: $dotnet_mscoree_marker"
  echo "[cage] .NET Framework 4.8 $label native CLR exists: $dotnet_clr_marker"
}}

# Install x64 before x86. Wine/.NET records the x86 product in a way that can make
# the x64 MSI report NEWERVERSIONDETECTED before 64-bit CLR markers are created.
install_dotnet_msi x64 "$netfx_msi_x64" "$dotnet_mscoree_marker_x64" "$dotnet_clr_marker_x64"
install_dotnet_msi x86 "$netfx_msi_x86" "$dotnet_mscoree_marker_x86" "$dotnet_clr_marker_x86"
echo "[cage] .NET Framework 4.8 MSI step complete"'''
        return BuildStep(commands=[script], description="Install .NET Framework 4.8 for Chocolatey", kind="wine-msiexec", timeout=1800)

    def _registry_prep_step(self) -> BuildStep:
        script = '''set -eu
unset WINEDLLOVERRIDES
echo "[cage] Preparing Wine registry for Chocolatey..."
pwsh_win='C:\\Program Files\\PowerShell\\7\\pwsh.exe'
timeout "${CAGE_WINECFG_TIMEOUT:-120s}" winecfg /v win10
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\DllOverrides' /v mscoree /t REG_SZ /d native /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\Software\\Microsoft\\.NETFramework' /v OnlyUseLatestCLR /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Microsoft\\.NETFramework\\Policy\\v2.0' /v 50727 /t REG_SZ /d 50727-50727 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.0' /v Install /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.0' /v SP /t REG_DWORD /d 2 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.0\\Setup' /v InstallSuccess /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.5' /v Install /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v3.5' /v SP /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Microsoft\\Avalon.Graphics' /v DisableHWAcceleration /t REG_DWORD /d 0 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Classes\\CLSID\\{0A29FF9E-7F9C-4437-8B11-F424491E3931}\\InprocServer32' /ve /t REG_SZ /d 'C:\\Windows\\System32\\mscoree.dll' /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\\SOFTWARE\\Classes\\CLSID\\{0A29FF9E-7F9C-4437-8B11-F424491E3931}\\InprocServer32' /v ThreadingModel /t REG_SZ /d Both /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Environment' /v PS7 /t REG_SZ /d "$pwsh_win" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v amsi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v dwmapi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v rpcrt4 /d native,builtin /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\choco.exe\\DllOverrides' /v mscoree /t REG_SZ /d native /f
echo "[cage] Wine registry prepared for Chocolatey"'''
        return BuildStep(commands=[script], description="Prepare Wine registry for Chocolatey", kind="wine-reg", timeout=120)

    def _finalize_step(self, wine_prefix: str, choco_exe: str, raw_choco_exe: str) -> BuildStep:
        script = f'''set -eu
echo "[cage] Promote Chocolatey natively"
wine_prefix="{wine_prefix}"
choco_exe="{choco_exe}"
raw_choco_exe="{raw_choco_exe}"
raw_choco_dir="$wine_prefix/drive_c/ProgramData/tools/ChocolateyInstall"
canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"
canonical_bin_dir="$canonical_choco_dir/bin"
tools_dir="$wine_prefix/drive_c/tools"
choco_dir_win='C:\\ProgramData\\chocolatey'
choco_tools_win='C:\\tools'

test -f "$raw_choco_exe"
echo "[cage] raw ChocolateyInstall payload is only a source: $raw_choco_exe"
rm -rf "$canonical_choco_dir"
python3 - "$raw_choco_dir" "$canonical_choco_dir" <<'PY'
import shutil
import sys
from pathlib import Path

source = Path(sys.argv[1])
dest = Path(sys.argv[2])
if not source.is_dir():
    raise SystemExit(f"missing raw Chocolatey source directory: {{source}}")
if not (source / "choco.exe").is_file():
    raise SystemExit(f"missing raw Chocolatey choco.exe: {{source / 'choco.exe'}}")
shutil.copytree(source, dest)
bin_dir = dest / "bin"
bin_dir.mkdir(parents=True, exist_ok=True)
redirects = dest / "redirects"
if redirects.is_dir():
    for item in redirects.iterdir():
        if not item.is_file():
            continue
        # Keep helper redirects such as RefreshEnv.cmd, but do not promote the
        # upstream redirect/shim choco.exe as canonical. Real Wine builds showed
        # that 147 KB redirect shim as the loader boundary that failed before
        # managed Chocolatey output. The canonical bin entry must be the real
        # root Chocolatey executable from the nupkg.
        if item.name.lower() == "choco.exe":
            continue
        shutil.copy2(item, bin_dir / item.name)
choco = bin_dir / "choco.exe"
root_choco = dest / "choco.exe"
if not root_choco.is_file():
    raise SystemExit(f"missing root Chocolatey choco.exe: {{root_choco}}")
shutil.copy2(root_choco, choco)
if choco.stat().st_size != root_choco.stat().st_size:
    raise SystemExit(f"canonical bin choco.exe size mismatch: {{choco}} != {{root_choco}}")
required = [
    dest / "helpers",
    dest / "tools",
    dest / "redirects",
    choco,
    root_choco,
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit("missing promoted Chocolatey payload: " + ", ".join(missing))
PY
mkdir -p "$tools_dir"
chmod +x "$choco_exe"
test -d "$canonical_choco_dir/helpers"
test -d "$canonical_choco_dir/tools"
test -d "$canonical_choco_dir/redirects"
test -f "$canonical_choco_dir/helpers/chocolateyInstaller.psm1"
test -f "$canonical_choco_dir/tools/7z.exe"
test -f "$canonical_choco_dir/redirects/choco.exe"
if [ ! -f "$choco_exe" ]; then
  echo "[cage] ERROR: native Chocolatey promotion did not create canonical choco.exe: $choco_exe"
  find "$wine_prefix/drive_c/ProgramData" -maxdepth 4 -iname '*choco*' 2>/dev/null | sort || true
  exit 1
fi

native_loader_mscoree="$wine_prefix/drive_c/windows/system32/mscoree.dll"
native_loader_ucrtbase="$wine_prefix/drive_c/windows/system32/ucrtbase_clr0400.dll"
native_loader_vcruntime="$wine_prefix/drive_c/windows/system32/vcruntime140_clr0400.dll"
for native_loader in "$native_loader_mscoree" "$native_loader_ucrtbase" "$native_loader_vcruntime"; do
  if [ ! -f "$native_loader" ]; then
    echo "[cage] ERROR: native CLR loader dependency missing before Chocolatey verification: $native_loader"
    exit 68
  fi
done
# The Windows loader failed before managed Chocolatey output even when native
# CLR marker files existed. Keep these native CLR loader dependencies app-local
# beside canonical choco.exe so IL-only import resolution does not depend on
# Wine's system DLL search path.
cp -f "$native_loader_mscoree" "$canonical_bin_dir/mscoree.dll"
cp -f "$native_loader_ucrtbase" "$canonical_bin_dir/ucrtbase_clr0400.dll"
cp -f "$native_loader_vcruntime" "$canonical_bin_dir/vcruntime140_clr0400.dll"
echo "[cage] App-local native CLR loader dependencies copied beside canonical choco.exe"

echo "[cage] Native Chocolatey promotion copied raw payload to canonical directory"
timeout "${{CAGE_WINE_REG_TIMEOUT:-120s}}" wine reg add 'HKCU\\Environment' /v ChocolateyInstall /t REG_SZ /d "$choco_dir_win" /f
timeout "${{CAGE_WINE_REG_TIMEOUT:-120s}}" wine reg add 'HKCU\\Environment' /v ChocolateyToolsLocation /t REG_SZ /d "$choco_tools_win" /f
export ChocolateyInstall="$choco_dir_win"
export ChocolateyToolsLocation="$choco_tools_win"
export WINEDLLOVERRIDES='mscoree=n'

verify_log="${{CAGE_BUNDLE_MOUNT:-/opt/cage}}/logs/chocolatey-verify.log"
mkdir -p "$(dirname "$verify_log")"
echo "[cage] Verifying canonical Chocolatey..."
set +e
timeout "${{CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}}" wine "$choco_exe" --version > "$verify_log" 2>&1
verify_rc="$?"
set -e
if [ "$verify_rc" -ne 0 ]; then
  echo "[cage] WARNING: canonical Chocolatey verification failed rc=$verify_rc; see $verify_log"
  echo "[cage] Continuing to diagnostic step for structured evidence"
  tail -80 "$verify_log" || true
else
  cat "$verify_log"
fi
echo "[cage] Chocolatey native promotion complete"'''
        return BuildStep(commands=[script], description="Promote Chocolatey natively", kind="raw-shell")

    def _diagnostic_step(self, wine_prefix: str, choco_exe: str, raw_choco_exe: str) -> BuildStep:
        script = '''set -eu
echo "[cage] Diagnose Chocolatey readiness"
wine_prefix="__WINE_PREFIX__"
choco_exe="__CHOCO_EXE__"
raw_choco_exe="__RAW_CHOCO_EXE__"
canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"
canonical_bin_dir="$canonical_choco_dir/bin"
native_mscoree="$wine_prefix/drive_c/windows/system32/mscoree.dll"
native_mscoreei="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/mscoreei.dll"
native_clr="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"
native_wow64_mscoree="$wine_prefix/drive_c/windows/syswow64/mscoree.dll"
native_wow64_mscoreei="$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/mscoreei.dll"
native_wow64_clr="$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/clr.dll"
native_ucrtbase="$wine_prefix/drive_c/windows/system32/ucrtbase_clr0400.dll"
native_vcruntime="$wine_prefix/drive_c/windows/system32/vcruntime140_clr0400.dll"
app_local_mscoree="$canonical_bin_dir/mscoree.dll"
app_local_ucrtbase="$canonical_bin_dir/ucrtbase_clr0400.dll"
app_local_vcruntime="$canonical_bin_dir/vcruntime140_clr0400.dll"
export ChocolateyInstall='C:\\ProgramData\\chocolatey'
export ChocolateyToolsLocation='C:\\tools'
export WINEDLLOVERRIDES='mscoree=n'
probe_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-diagnostics"
diagnostic_json="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-diagnostic.json"
mkdir -p "$probe_dir" "$(dirname "$diagnostic_json")"

set +e
winepath -w "$choco_exe" > "$probe_dir/winepath-canonical.log" 2>&1
winepath_rc="$?"
wine cmd /c dir 'C:\\ProgramData\\chocolatey\\bin' > "$probe_dir/cmd-dir-chocolatey-bin.log" 2>&1
cmd_dir_rc="$?"
wine cmd /c echo CAGE-CMD-OK > "$probe_dir/cmd-echo.log" 2>&1
cmd_echo_rc="$?"
wine reg query 'HKCU\\Environment' /v ChocolateyInstall > "$probe_dir/registry-chocolatey-install.log" 2>&1
registry_install_rc="$?"
wine reg query 'HKCU\\Environment' /v ChocolateyToolsLocation > "$probe_dir/registry-chocolatey-tools.log" 2>&1
registry_tools_rc="$?"
wine reg query 'HKCU\\Software\\Wine\\DllOverrides' /v mscoree > "$probe_dir/registry-wine-mscoree.log" 2>&1
wine_dll_mscoree_rc="$?"
wine reg query 'HKLM\\Software\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full' /v Release > "$probe_dir/registry-dotnet48-release.log" 2>&1
dotnet_release_rc="$?"
test -f "$native_mscoree"
native_mscoree_rc="$?"
test -f "$native_mscoreei"
native_mscoreei_rc="$?"
test -f "$native_clr"
native_clr_rc="$?"
test -f "$native_wow64_mscoree"
native_wow64_mscoree_rc="$?"
test -f "$native_wow64_mscoreei"
native_wow64_mscoreei_rc="$?"
test -f "$native_wow64_clr"
native_wow64_clr_rc="$?"
test -f "$native_ucrtbase"
native_ucrtbase_rc="$?"
test -f "$native_vcruntime"
native_vcruntime_rc="$?"
test -f "$app_local_mscoree"
app_local_mscoree_rc="$?"
test -f "$app_local_ucrtbase"
app_local_ucrtbase_rc="$?"
test -f "$app_local_vcruntime"
app_local_vcruntime_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" --version > "$probe_dir/choco-version.log" 2>&1
choco_version_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine cmd /c 'C:\\ProgramData\\chocolatey\\bin\\choco.exe --version' > "$probe_dir/choco-version-cmd.log" 2>&1
choco_version_cmd_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" source list > "$probe_dir/choco-source-list.log" 2>&1
choco_source_rc="$?"
WINEDEBUG=+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe" --version > "$probe_dir/choco-mscoree-loader.log" 2>&1
choco_loader_rc="$?"
if [ "$choco_version_rc" -ne 0 ] && [ ! -s "$probe_dir/choco-version.log" ]; then
  WINEDEBUG=+seh,+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe" --version > "$probe_dir/choco-version-winedebug.log" 2>&1 || true
fi
python3 - "$canonical_choco_dir" > "$probe_dir/promoted-files.log" 2>&1 <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    print(f"{path.stat().st_size}\t{path}")
PY
set -e

python3 - "$diagnostic_json" "$choco_exe" "$raw_choco_exe" "$canonical_choco_dir" "$native_mscoree" "$native_mscoreei" "$native_clr" "$native_wow64_mscoree" "$native_wow64_mscoreei" "$native_wow64_clr" "$native_ucrtbase" "$native_vcruntime" "$app_local_mscoree" "$app_local_ucrtbase" "$app_local_vcruntime" "$winepath_rc" "$cmd_dir_rc" "$cmd_echo_rc" "$registry_install_rc" "$registry_tools_rc" "$wine_dll_mscoree_rc" "$dotnet_release_rc" "$native_mscoree_rc" "$native_mscoreei_rc" "$native_clr_rc" "$native_wow64_mscoree_rc" "$native_wow64_mscoreei_rc" "$native_wow64_clr_rc" "$native_ucrtbase_rc" "$native_vcruntime_rc" "$app_local_mscoree_rc" "$app_local_ucrtbase_rc" "$app_local_vcruntime_rc" "$choco_version_rc" "$choco_version_cmd_rc" "$choco_source_rc" "$choco_loader_rc" <<'PY'
import json
import sys
from pathlib import Path

(
    diagnostic_json,
    choco_exe,
    raw_choco_exe,
    canonical_choco_dir,
    native_mscoree,
    native_mscoreei,
    native_clr,
    native_wow64_mscoree,
    native_wow64_mscoreei,
    native_wow64_clr,
    native_ucrtbase,
    native_vcruntime,
    app_local_mscoree,
    app_local_ucrtbase,
    app_local_vcruntime,
    winepath_rc,
    cmd_dir_rc,
    cmd_echo_rc,
    registry_install_rc,
    registry_tools_rc,
    wine_dll_mscoree_rc,
    dotnet_release_rc,
    native_mscoree_rc,
    native_mscoreei_rc,
    native_clr_rc,
    native_wow64_mscoree_rc,
    native_wow64_mscoreei_rc,
    native_wow64_clr_rc,
    native_ucrtbase_rc,
    native_vcruntime_rc,
    app_local_mscoree_rc,
    app_local_ucrtbase_rc,
    app_local_vcruntime_rc,
    choco_version_rc,
    choco_version_cmd_rc,
    choco_source_rc,
    choco_loader_rc,
) = sys.argv[1:]
canonical = Path(choco_exe)
raw = Path(raw_choco_exe)
canonical_dir = Path(canonical_choco_dir)
root_choco = canonical_dir / "choco.exe"
redirect_choco = canonical_dir / "redirects" / "choco.exe"
app_local_mscoree_path = Path(app_local_mscoree)
app_local_ucrtbase_path = Path(app_local_ucrtbase)
app_local_vcruntime_path = Path(app_local_vcruntime)

def file_size(path: Path) -> int | None:
    return path.stat().st_size if path.is_file() else None

checks = {
    "canonicalChocoExists": canonical.is_file(),
    "rawToolsPayloadExists": raw.is_file(),
    "redirectExists": (canonical_dir / "redirects" / "choco.exe").is_file(),
    "winepathCanonical": winepath_rc == "0",
    "wineCmdEcho": cmd_echo_rc == "0",
    "cmdDirCanonicalBin": cmd_dir_rc == "0",
    "registryEnvironment": registry_install_rc == "0" and registry_tools_rc == "0",
    "wineDllOverridesMscoree": wine_dll_mscoree_rc == "0",
    "dotnetReleaseRegistry": dotnet_release_rc == "0",
    "nativeMscoreeExists": native_mscoree_rc == "0" and Path(native_mscoree).is_file(),
    "nativeMscoreeiExists": native_mscoreei_rc == "0" and Path(native_mscoreei).is_file(),
    "nativeClrExists": native_clr_rc == "0" and Path(native_clr).is_file(),
    "nativeWow64MscoreeExists": native_wow64_mscoree_rc == "0" and Path(native_wow64_mscoree).is_file(),
    "nativeWow64MscoreeiExists": native_wow64_mscoreei_rc == "0" and Path(native_wow64_mscoreei).is_file(),
    "nativeWow64ClrExists": native_wow64_clr_rc == "0" and Path(native_wow64_clr).is_file(),
    "nativeUcrtbaseClrExists": native_ucrtbase_rc == "0" and Path(native_ucrtbase).is_file(),
    "nativeVcruntimeClrExists": native_vcruntime_rc == "0" and Path(native_vcruntime).is_file(),
    "appLocalMscoreeExists": app_local_mscoree_rc == "0" and Path(app_local_mscoree).is_file(),
    "appLocalUcrtbaseClrExists": app_local_ucrtbase_rc == "0" and Path(app_local_ucrtbase).is_file(),
    "appLocalVcruntimeClrExists": app_local_vcruntime_rc == "0" and Path(app_local_vcruntime).is_file(),
    "chocoVersion": choco_version_rc == "0",
    "chocoVersionViaCmd": choco_version_cmd_rc == "0",
    "sourceList": choco_source_rc == "0",
    "mscoreeLoader": choco_loader_rc == "0",
}
payload = {
    "schemaVersion": "cage.chocolatey-diagnostic/v0",
    "phase": "Chocolatey diagnostic",
    "status": "passed" if all(checks.values()) else "failed",
    "checks": checks,
    "paths": {
        "canonicalChoco": choco_exe,
        "rawToolsPayload": raw_choco_exe,
        "nativeMscoree": native_mscoree,
        "nativeMscoreei": native_mscoreei,
        "nativeClr": native_clr,
        "nativeWow64Mscoree": native_wow64_mscoree,
        "nativeWow64Mscoreei": native_wow64_mscoreei,
        "nativeWow64Clr": native_wow64_clr,
        "nativeUcrtbaseClr": native_ucrtbase,
        "nativeVcruntimeClr": native_vcruntime,
        "appLocalMscoree": app_local_mscoree,
        "appLocalUcrtbaseClr": app_local_ucrtbase,
        "appLocalVcruntimeClr": app_local_vcruntime,
        "logDirectory": "logs/chocolatey-diagnostics",
    },
    "fileSizes": {
        "canonicalChoco": file_size(canonical),
        "rootChoco": file_size(root_choco),
        "redirectChoco": file_size(redirect_choco),
        "rawToolsPayload": file_size(raw),
        "nativeMscoree": file_size(Path(native_mscoree)),
        "nativeUcrtbaseClr": file_size(Path(native_ucrtbase)),
        "nativeVcruntimeClr": file_size(Path(native_vcruntime)),
        "appLocalMscoree": file_size(app_local_mscoree_path),
        "appLocalUcrtbaseClr": file_size(app_local_ucrtbase_path),
        "appLocalVcruntimeClr": file_size(app_local_vcruntime_path),
    },
    "logs": {
        "chocoVersion": "logs/chocolatey-diagnostics/choco-version.log",
        "chocoVersionViaCmd": "logs/chocolatey-diagnostics/choco-version-cmd.log",
        "chocoVersionWineDebug": "logs/chocolatey-diagnostics/choco-version-winedebug.log",
        "chocoMscoreeLoader": "logs/chocolatey-diagnostics/choco-mscoree-loader.log",
        "wineDllOverridesMscoree": "logs/chocolatey-diagnostics/registry-wine-mscoree.log",
        "dotnetReleaseRegistry": "logs/chocolatey-diagnostics/registry-dotnet48-release.log",
        "promotedFiles": "logs/chocolatey-diagnostics/promoted-files.log",
    },
}
Path(diagnostic_json).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
PY

choco_diag_status="$(python3 - "$diagnostic_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("status", "failed"))
PY
)"
if [ "$choco_diag_status" != "passed" ]; then
  echo "[cage] ERROR: Chocolatey diagnostics failed; see $diagnostic_json"
  echo "[cage] Chocolatey version log tail:"
  tail -80 "$probe_dir/choco-version.log" || true
  echo "[cage] Chocolatey mscoree loader tail:"
  tail -120 "$probe_dir/choco-mscoree-loader.log" || true
  if [ -f "$probe_dir/choco-version-winedebug.log" ]; then
    echo "[cage] Chocolatey WINEDEBUG tail:"
    tail -120 "$probe_dir/choco-version-winedebug.log" || true
  fi
  exit 69
fi
echo "[cage] Chocolatey diagnostics passed"'''.replace("__WINE_PREFIX__", wine_prefix).replace("__CHOCO_EXE__", choco_exe).replace("__RAW_CHOCO_EXE__", raw_choco_exe)
        return BuildStep(
            commands=[script],
            description="Diagnose Chocolatey readiness",
            kind="wine-run",
            timeout=120,
            metadata={"diagnostic": "metadata/chocolatey-diagnostic.json"},
        )

    def _package_install_step(self, choco_exe: str, package_args: str, source_arg: str) -> BuildStep:
        script = f'''set -eu
echo "[cage] Install Chocolatey packages"
choco_exe="{choco_exe}"
export ChocolateyInstall='C:\\ProgramData\\chocolatey'
export ChocolateyToolsLocation='C:\\tools'
export WINEDLLOVERRIDES='mscoree=n'
diagnostic_json="${{CAGE_BUNDLE_MOUNT:-/opt/cage}}/metadata/chocolatey-diagnostic.json"
if [ ! -f "$choco_exe" ]; then
  echo "[cage] ERROR: choco.exe is missing before package install: $choco_exe"
  exit 1
fi
choco_diag_status="$(python3 - "$diagnostic_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("status", "failed"))
PY
)"
if [ "$choco_diag_status" != "passed" ]; then
  echo "[cage] ERROR: refusing package install because Chocolatey diagnostics did not pass: $choco_diag_status"
  exit 69
fi
logs_dir="${{CAGE_BUNDLE_MOUNT:-/opt/cage}}/logs/chocolatey"
mkdir -p "$logs_dir"
powershell_host_log="$logs_dir/chocolatey-feature-powershellHost.log"
global_confirmation_log="$logs_dir/chocolatey-feature-allowGlobalConfirmation.log"
echo "[cage] Applying upstream Chocolatey feature policy before package install..."
set +e
timeout "${{CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-120s}}" wine "$choco_exe" feature disable --name=powershellHost > "$powershell_host_log" 2>&1
powershell_host_rc="$?"
timeout "${{CAGE_CHOCOLATEY_FEATURE_TIMEOUT:-120s}}" wine "$choco_exe" feature enable -n allowGlobalConfirmation > "$global_confirmation_log" 2>&1
global_confirmation_rc="$?"
set -e
if [ "$powershell_host_rc" -ne 0 ]; then
  echo "[cage] ERROR: failed to disable Chocolatey's built-in PowerShell host; see $powershell_host_log"
  tail -120 "$powershell_host_log" || true
  exit "$powershell_host_rc"
fi
if [ "$global_confirmation_rc" -ne 0 ]; then
  echo "[cage] ERROR: failed to enable Chocolatey global confirmation; see $global_confirmation_log"
  tail -120 "$global_confirmation_log" || true
  exit "$global_confirmation_rc"
fi
echo "[cage] Installing Chocolatey packages: {package_args}"
timeout "${{CAGE_CHOCOLATEY_INSTALL_TIMEOUT:-1800s}}" wine "$choco_exe" install {package_args} -y{source_arg}'''
        return BuildStep(
            commands=[script],
            description=f"Install Chocolatey packages: {package_args}",
            kind="wine-run",
            timeout=1800,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.install is not None:
            result["install"] = self.install
        if self.source is not None:
            result["source"] = self.source
        if self.version != DEFAULT_CHOCOLATEY_FOR_WINE_VERSION:
            result["version"] = self.version
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        return result
