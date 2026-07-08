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
from .powershell_engine import powershell_engine_steps
from ..build_step import BuildStep

DEFAULT_CHOCOLATEY_FOR_WINE_VERSION = "v0.5c.755"
DEFAULT_CHOCOLATEY_FOR_WINE_SHA256 = "87f4ecc08a9b22f16aa5633ca107c151ddf3fed0b256fed9fb99680af7095d14"
DEFAULT_CHOCOLATEY_VERSION = "2.6.0"
DEFAULT_CHOCOLATEY_NUPKG_SHA256 = "f13a2af9cd4ec2c9b58d81861bc95ad7151e3a871d8f758dffa72a996a3792d8"
DEFAULT_CFW_WINETRICKS_SHA256 = "1d74ffad96f2052d42a0fa3c7ac5dbc8d099e7ad9f9aba3213446a25b34ff48c"
DEFAULT_DOTNET48_SHA256 = "0a3a390c47e639d0f7fc65b21195fee6b7f65b066f80f70c60fab191d14b7e40"


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

    def build(self) -> list[BuildStep]:
        """Generate deterministic Chocolatey setup and package install steps."""
        if not self.install:
            raise ModuleError("chocolatey module requires 'install' field")

        packages = self.install.get("packages", [])
        if not packages:
            raise ModuleError("chocolatey module 'install.packages' cannot be empty")

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
            *powershell_engine_steps(wine_prefix=wine_prefix, version_slot="7"),
            self._prepare_chocolatey_data_step(wine_prefix, raw_choco_exe),
            self._dotnet48_step(wine_prefix),
            self._registry_prep_step(),
            self._finalize_step(wine_prefix, choco_exe, raw_choco_exe),
            self._package_install_step(choco_exe, package_args, source_arg),
        ]

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
extract_7z_archive "$cfw_extract/c_drive.7z" "$wine_prefix/drive_c"

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
        return BuildStep(commands=[script], description="Prepare Chocolatey-for-wine data")

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
if [ "$dotnet_msi_rc" -ne 0 ]; then
  if [ -f "$dotnet_success_marker" ] && grep -qE 'Action ended .*INSTALL[.] Return value 0' "$dotnet_msiexec_log"; then
    echo "[cage] .NET Framework 4.8 MSI log reports INSTALL success and marker exists; ignoring Wine msiexec exit $dotnet_msi_rc"
  else
    echo "[cage] ERROR: .NET Framework 4.8 MSI failed with exit code $dotnet_msi_rc"
    echo "[cage] ERROR: missing success marker or MSI success log: $dotnet_success_marker"
    exit "$dotnet_msi_rc"
  fi
fi
if [ ! -f "$dotnet_success_marker" ]; then
  echo "[cage] ERROR: .NET Framework 4.8 marker missing after MSI step: $dotnet_success_marker"
  exit 67
fi
echo "[cage] .NET Framework 4.8 MSI step complete"'''
        return BuildStep(commands=[script], description="Install .NET Framework 4.8 for Chocolatey")

    def _registry_prep_step(self) -> BuildStep:
        script = '''set -eu
unset WINEDLLOVERRIDES
echo "[cage] Preparing Wine registry for Chocolatey..."
timeout "${CAGE_WINECFG_TIMEOUT:-120s}" winecfg /v win10
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v amsi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v dwmapi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides' /v rpcrt4 /d native,builtin /f
echo "[cage] Wine registry prepared for Chocolatey"'''
        return BuildStep(commands=[script], description="Prepare Wine registry for Chocolatey")

    def _finalize_step(self, wine_prefix: str, choco_exe: str, raw_choco_exe: str) -> BuildStep:
        script = f'''set -eu
unset WINEDLLOVERRIDES
echo "[cage] Finalize Chocolatey-for-wine"
wine_prefix="{wine_prefix}"
choco_exe="{choco_exe}"
raw_choco_exe="{raw_choco_exe}"
pwsh_exe="$wine_prefix/drive_c/Program Files/PowerShell/7/pwsh.exe"
cfw_dir="$wine_prefix/drive_c/ProgramData/Chocolatey-for-wine"
choc_install_ps1="$cfw_dir/choc_install.ps1"
work_dir="/tmp/cage-chocolatey-finalize"
finalize_driver="$work_dir/finalize-chocolatey-for-wine.ps1"
finalize_log="$work_dir/chocolatey-finalize.log"
pwsh_probe_log="$work_dir/pwsh-probe.log"
pwsh_probe_sentinel="$work_dir/pwsh-probe-ok.txt"
mkdir -p "$work_dir"

test -f "$pwsh_exe"
test -f "$raw_choco_exe"
test -f "$choc_install_ps1"

pwsh_probe_sentinel_win="$(winepath -w "$pwsh_probe_sentinel")"
rm -f "$pwsh_probe_sentinel"
: > "$pwsh_probe_log"
echo "[cage] Probing Chocolatey PowerShell engine..."
set +e
timeout 120s wine "$pwsh_exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "[System.IO.File]::WriteAllText('$pwsh_probe_sentinel_win','ok'); [Console]::Out.WriteLine('[cage] pwsh probe OK'); \\$PSVersionTable.PSVersion.ToString()" > "$pwsh_probe_log" 2>&1
pwsh_probe_rc="$?"
set -e
if [ -s "$pwsh_probe_log" ]; then
  sed 's/^/[cfw-pwsh] /' "$pwsh_probe_log"
fi
if [ "$pwsh_probe_rc" -ne 0 ]; then
  echo "[cage] ERROR: PowerShell probe failed with exit code $pwsh_probe_rc"
  exit "$pwsh_probe_rc"
fi
if [ ! -f "$pwsh_probe_sentinel" ]; then
  echo "[cage] ERROR: PowerShell probe did not create sentinel: $pwsh_probe_sentinel"
  exit 98
fi
if [ ! -s "$pwsh_probe_log" ]; then
  echo "[cage] PowerShell probe produced no captured stdout; continuing because sentinel exists"
fi

cfw_dir_win="$(winepath -w "$cfw_dir")"
choc_install_ps1_win="$(winepath -w "$choc_install_ps1")"
choco_exe_win="$(winepath -w "$choco_exe")"
finalize_driver_win="$(winepath -w "$finalize_driver")"
cat > "$finalize_driver" <<'PS1'
$ErrorActionPreference = 'Stop'
$scriptPath = $args[0]
$cfwDir = $args[1]
$chocoExe = $args[2]
Write-Host "[cage] Running upstream choc_install.ps1: $scriptPath"
& $scriptPath $cfwDir '/q'
if (!(Test-Path $chocoExe)) {{
    throw "Chocolatey-for-wine finalizer did not create canonical choco.exe: $chocoExe"
}}
Write-Host "[cage] Upstream Chocolatey-for-wine finalizer completed"
PS1

set +e
timeout "${{CAGE_CHOCOLATEY_FINALIZE_TIMEOUT:-1200s}}" wine "$pwsh_exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$finalize_driver_win" "$choc_install_ps1_win" "$cfw_dir_win" "$choco_exe_win" > "$finalize_log" 2>&1
finalize_rc="$?"
set -e
if [ -s "$finalize_log" ]; then
  sed 's/^/[cfw-finalize] /' "$finalize_log"
fi
if [ "$finalize_rc" -ne 0 ]; then
  echo "[cage] ERROR: Chocolatey-for-wine finalizer failed with exit code $finalize_rc"
  exit "$finalize_rc"
fi
if [ ! -f "$choco_exe" ]; then
  echo "[cage] ERROR: Chocolatey-for-wine finalizer returned success but left choco.exe missing: $choco_exe"
  if [ ! -s "$finalize_log" ]; then
    echo "[cage] Finalizer log was empty"
  fi
  find "$wine_prefix/drive_c/ProgramData" -maxdepth 4 -iname '*choco*' 2>/dev/null | sort || true
  exit 1
fi

echo "[cage] Verifying Chocolatey..."
timeout 120s wine "$choco_exe" --version
echo "[cage] Chocolatey finalization complete"'''
        return BuildStep(commands=[script], description="Finalize Chocolatey-for-wine")

    def _package_install_step(self, choco_exe: str, package_args: str, source_arg: str) -> BuildStep:
        script = f'''set -eu
unset WINEDLLOVERRIDES
choco_exe="{choco_exe}"
if [ ! -f "$choco_exe" ]; then
  echo "[cage] ERROR: choco.exe is missing before package install: $choco_exe"
  exit 1
fi
echo "[cage] Installing Chocolatey packages: {package_args}"
wine "$choco_exe" install {package_args} -y{source_arg}'''
        return BuildStep(commands=[script], description=f"Install Chocolatey packages: {package_args}")

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
