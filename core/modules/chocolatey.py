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
netfx_msi="$dotnet_extract/netfx_Full_x64.msi"
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
if [ ! -f "$netfx_msi" ]; then
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
test -f "$netfx_msi"
dotnet_success_marker="$wine_prefix/drive_c/windows/system32/ucrtbase_clr0400.dll"
netfx_msi_win="$(winepath -w "$netfx_msi")"
dotnet_msiexec_log="$dotnet_cache/dotnet48-msiexec.log"
dotnet_msiexec_log_win="$(winepath -w "$dotnet_msiexec_log")"
rm -f "$dotnet_msiexec_log"
echo "[cage] Installing .NET Framework 4.8 from dedicated MSI step..."
echo "[cage] .NET Framework 4.8 MSI: $netfx_msi_win"
set +e
timeout "${{CAGE_DOTNET48_TIMEOUT:-1800s}}" wine msiexec /i "$netfx_msi_win" MSIFASTINSTALL=2 DISABLEROLLBACK=1 /QN /NORESTART /L*v "$dotnet_msiexec_log_win"
dotnet_msi_rc="$?"
set -e
if [ -f "$dotnet_msiexec_log" ]; then
  echo "[cage] .NET Framework 4.8 MSI failure markers:"
  grep -nEi 'Return value 3|MainEngineThread|Error [0-9]+|Fatal error' "$dotnet_msiexec_log" | head -80 | sed 's/^/[dotnet48-msi-marker] /' || true
  echo "[cage] .NET Framework 4.8 MSI log tail:"
  tail -120 "$dotnet_msiexec_log" | sed 's/^/[dotnet48-msi] /'
fi
dotnet_msi_success=0
if [ -f "$dotnet_msiexec_log" ] && grep -qE 'Action ended .*INSTALL[.] Return value 1' "$dotnet_msiexec_log"; then
  dotnet_msi_success=1
fi
if [ "$dotnet_msi_success" -ne 1 ]; then
  echo "[cage] ERROR: .NET Framework 4.8 MSI did not report INSTALL success"
  if [ "$dotnet_msi_rc" -ne 0 ]; then
    echo "[cage] ERROR: Wine msiexec exit code: $dotnet_msi_rc"
    exit "$dotnet_msi_rc"
  fi
  exit 67
fi
if [ "$dotnet_msi_rc" -ne 0 ]; then
  echo "[cage] .NET Framework 4.8 MSI log reports INSTALL success; ignoring Wine msiexec exit $dotnet_msi_rc"
fi
if [ -f "$dotnet_success_marker" ]; then
  echo "[cage] .NET Framework 4.8 marker exists: $dotnet_success_marker"
else
  echo "[cage] .NET Framework 4.8 marker not present after MSI success: $dotnet_success_marker"
  echo "[cage] Continuing; finalizer patch skips Chocolatey-for-wine's unbounded marker wait"
fi
echo "[cage] .NET Framework 4.8 MSI step complete"'''
        return BuildStep(commands=[script], description="Install .NET Framework 4.8 for Chocolatey", kind="wine-msiexec", timeout=1800)

    def _registry_prep_step(self) -> BuildStep:
        script = '''set -eu
unset WINEDLLOVERRIDES
echo "[cage] Preparing Wine registry for Chocolatey..."
pwsh_win='C:\\Program Files\\PowerShell\\7\\pwsh.exe'
timeout "${CAGE_WINECFG_TIMEOUT:-120s}" winecfg /v win10
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Environment' /v PS7 /t REG_SZ /d "$pwsh_win" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v amsi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v dwmapi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v rpcrt4 /d native,builtin /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\choco.exe\\DllOverrides' /v mscoree /d native,builtin /f
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
        if item.is_file():
            shutil.copy2(item, bin_dir / item.name)
choco = bin_dir / "choco.exe"
root_choco = dest / "choco.exe"
if not choco.is_file() and root_choco.is_file():
    shutil.copy2(root_choco, choco)
required = [
    dest / "helpers",
    dest / "tools",
    dest / "redirects",
    choco,
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

echo "[cage] Native Chocolatey promotion copied raw payload to canonical directory"
timeout "${{CAGE_WINE_REG_TIMEOUT:-120s}}" wine reg add 'HKCU\\Environment' /v ChocolateyInstall /t REG_SZ /d "$choco_dir_win" /f
timeout "${{CAGE_WINE_REG_TIMEOUT:-120s}}" wine reg add 'HKCU\\Environment' /v ChocolateyToolsLocation /t REG_SZ /d "$choco_tools_win" /f
export ChocolateyInstall="$choco_dir_win"
export ChocolateyToolsLocation="$choco_tools_win"
export WINEDLLOVERRIDES='mscoree=native,builtin'

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
export ChocolateyInstall='C:\\ProgramData\\chocolatey'
export ChocolateyToolsLocation='C:\\tools'
export WINEDLLOVERRIDES='mscoree=native,builtin'
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
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" --version > "$probe_dir/choco-version.log" 2>&1
choco_version_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine cmd /c 'C:\\ProgramData\\chocolatey\\bin\\choco.exe --version' > "$probe_dir/choco-version-cmd.log" 2>&1
choco_version_cmd_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" source list > "$probe_dir/choco-source-list.log" 2>&1
choco_source_rc="$?"
if [ "$choco_version_rc" -ne 0 ] && [ ! -s "$probe_dir/choco-version.log" ]; then
  WINEDEBUG=+seh,+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe" --version > "$probe_dir/choco-version-winedebug.log" 2>&1 || true
fi
find "$canonical_choco_dir" -maxdepth 3 -type f | sort > "$probe_dir/promoted-files.log" 2>&1 || true
set -e

python3 - "$diagnostic_json" "$choco_exe" "$raw_choco_exe" "$canonical_choco_dir" "$winepath_rc" "$cmd_dir_rc" "$cmd_echo_rc" "$registry_install_rc" "$registry_tools_rc" "$choco_version_rc" "$choco_version_cmd_rc" "$choco_source_rc" <<'PY'
import json
import sys
from pathlib import Path

(
    diagnostic_json,
    choco_exe,
    raw_choco_exe,
    canonical_choco_dir,
    winepath_rc,
    cmd_dir_rc,
    cmd_echo_rc,
    registry_install_rc,
    registry_tools_rc,
    choco_version_rc,
    choco_version_cmd_rc,
    choco_source_rc,
) = sys.argv[1:]
canonical = Path(choco_exe)
raw = Path(raw_choco_exe)
canonical_dir = Path(canonical_choco_dir)
checks = {
    "canonicalChocoExists": canonical.is_file(),
    "rawToolsPayloadExists": raw.is_file(),
    "redirectExists": (canonical_dir / "redirects" / "choco.exe").is_file(),
    "winepathCanonical": winepath_rc == "0",
    "wineCmdEcho": cmd_echo_rc == "0",
    "cmdDirCanonicalBin": cmd_dir_rc == "0",
    "registryEnvironment": registry_install_rc == "0" and registry_tools_rc == "0",
    "chocoVersion": choco_version_rc == "0",
    "chocoVersionViaCmd": choco_version_cmd_rc == "0",
    "sourceList": choco_source_rc == "0",
}
payload = {
    "schemaVersion": "cage.chocolatey-diagnostic/v0",
    "phase": "Chocolatey diagnostic",
    "status": "passed" if all(checks.values()) else "failed",
    "checks": checks,
    "paths": {
        "canonicalChoco": choco_exe,
        "rawToolsPayload": raw_choco_exe,
        "logDirectory": "logs/chocolatey-diagnostics",
    },
    "logs": {
        "chocoVersion": "logs/chocolatey-diagnostics/choco-version.log",
        "chocoVersionViaCmd": "logs/chocolatey-diagnostics/choco-version-cmd.log",
        "chocoVersionWineDebug": "logs/chocolatey-diagnostics/choco-version-winedebug.log",
        "promotedFiles": "logs/chocolatey-diagnostics/promoted-files.log",
    },
}
Path(diagnostic_json).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
export WINEDLLOVERRIDES='mscoree=native,builtin'
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
