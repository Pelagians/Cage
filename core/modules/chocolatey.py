"""Chocolatey package manager module for Wine environments.

Chocolatey on Wine uses Piet Jankbal's Chocolatey-for-wine installer as the
source of truth. That project installs the PowerShell/CoreCLR pieces and Wine
compatibility shims Chocolatey needs. It intentionally does not depend on
Cage's separate powershell-wrapper module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ModuleBase, ModuleError


DEFAULT_CHOCOLATEY_FOR_WINE_VERSION = "v0.5c.755"
DEFAULT_CHOCOLATEY_FOR_WINE_SHA256 = "87f4ecc08a9b22f16aa5633ca107c151ddf3fed0b256fed9fb99680af7095d14"


def _sh_single_quote(value: str) -> str:
    """Quote a value for POSIX shell single-quoted context."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


@dataclass
class ChocolateyModule(ModuleBase):
    """Install Chocolatey packages through Chocolatey-for-wine.

    This module is self-contained for now: it downloads Chocolatey-for-wine,
    clears inherited build-time DLL overrides that break CLR setup, runs the
    Chocolatey-for-wine installer, verifies choco.exe, then installs packages.
    It is intentionally incompatible with the separate powershell-wrapper
    module until the wrapper compatibility layer is reconciled.
    """

    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None
    version: str = DEFAULT_CHOCOLATEY_FOR_WINE_VERSION
    sha256: str | None = None

    def build(self) -> list:
        """Generate build steps for Chocolatey-for-wine and package installs."""
        from ..build_step import BuildStep

        if not self.install:
            raise ModuleError("chocolatey module requires 'install' field")

        packages = self.install.get("packages", [])
        if not packages:
            raise ModuleError("chocolatey module 'install.packages' cannot be empty")

        import re

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
        release_url = (
            "https://github.com/PietJankbal/Chocolatey-for-wine/releases/download/"
            f"{self.version}/Chocolatey-for-wine.7z"
        )
        expected_sha = self.sha256
        if expected_sha is None and self.version == DEFAULT_CHOCOLATEY_FOR_WINE_VERSION:
            expected_sha = DEFAULT_CHOCOLATEY_FOR_WINE_SHA256

        expected_sha_script = expected_sha or ""
        package_args = " ".join(packages)
        source_arg = f" -s {_sh_single_quote(self.source)}" if self.source else ""

        install_commands = [
            f'''if [ ! -f "{choco_exe}" ]; then
  set -eu
  export WINEDLLOVERRIDES=""
  wine_prefix="{wine_prefix}"
  choco_exe="{choco_exe}"
  work_dir="/tmp/chocolatey-for-wine"
  extract_dir="$work_dir/extracted"
  archive="$work_dir/Chocolatey-for-wine.7z"
  expected_sha="{expected_sha_script}"

  echo "[cage] Chocolatey not found, installing Chocolatey-for-wine {self.version}..."
  rm -rf "$work_dir"
  mkdir -p "$extract_dir"

  echo "[cage] Downloading Chocolatey-for-wine {self.version}..."
  curl -fL --retry 3 -o "$archive" "{release_url}"

  if [ -n "$expected_sha" ]; then
    actual_sha="$(sha256sum "$archive" | cut -d ' ' -f 1)"
    if [ "$actual_sha" != "$expected_sha" ]; then
      echo "[cage] ERROR: Chocolatey-for-wine checksum mismatch"
      echo "[cage]   expected: $expected_sha"
      echo "[cage]   actual:   $actual_sha"
      exit 1
    fi
  fi

  echo "[cage] Extracting Chocolatey-for-wine..."
  if command -v 7z >/dev/null 2>&1; then
    7z x -y "$archive" "-o$extract_dir"
  elif command -v 7zz >/dev/null 2>&1; then
    7zz x -y "$archive" "-o$extract_dir"
  elif command -v 7za >/dev/null 2>&1; then
    7za x -y "$archive" "-o$extract_dir"
  else
    python3 - "$archive" "$extract_dir" <<'PY'
import sys
import py7zr
archive, dest = sys.argv[1], sys.argv[2]
with py7zr.SevenZipFile(archive, mode="r") as zf:
    zf.extractall(dest)
PY
  fi

  installer="$(find "$extract_dir" -name "ChoCinstaller_*.exe" -type f | head -n 1)"
  if [ -z "$installer" ]; then
    echo "[cage] ERROR: Could not find Chocolatey-for-wine ChoCinstaller_*.exe"
    find "$extract_dir" -maxdepth 3 -type f | sort
    exit 1
  fi

  cfw_dir="$(dirname "$installer")"
  choc_install_ps1="$cfw_dir/choc_install.ps1"
  pwsh_exe="$wine_prefix/drive_c/Program Files/PowerShell/7/pwsh.exe"
  raw_choco_exe="$wine_prefix/drive_c/ProgramData/tools/chocolateyInstall/choco.exe"

  echo "[cage] Setting Wine Windows version to win10 for Chocolatey-for-wine..."
  timeout "${{CAGE_WINECFG_TIMEOUT:-120s}}" winecfg /v win10

  echo "[cage] Running Chocolatey-for-wine installer: $installer"
  timeout "${{CAGE_CHOCOLATEY_INSTALL_TIMEOUT:-1200s}}" wine "$installer" /q

  if [ ! -f "$choco_exe" ] && [ -f "$raw_choco_exe" ]; then
    echo "[cage] Finalizing partial Chocolatey-for-wine install..."
    if [ ! -f "$pwsh_exe" ]; then
      echo "[cage] ERROR: partial Chocolatey extraction found, but pwsh.exe is missing: $pwsh_exe"
      find "$wine_prefix/drive_c" -maxdepth 5 -iname 'pwsh.exe' 2>/dev/null | sort || true
      exit 1
    fi
    if [ ! -f "$choc_install_ps1" ]; then
      echo "[cage] ERROR: partial Chocolatey extraction found, but choc_install.ps1 is missing: $choc_install_ps1"
      find "$cfw_dir" -maxdepth 2 -type f | sort || true
      exit 1
    fi

    cfw_dir_win="$(winepath -w "$cfw_dir")"
    choc_install_ps1_win="$(winepath -w "$choc_install_ps1")"
    choco_exe_win="$(winepath -w "$choco_exe")"
    finalize_driver="$work_dir/finalize-chocolatey-for-wine.ps1"
    finalize_driver_win="$(winepath -w "$finalize_driver")"
    finalize_log="$work_dir/chocolatey-finalize.log"
    pwsh_probe_log="$work_dir/pwsh-probe.log"
    pwsh_zip_repair_log="$work_dir/pwsh-zip-repair.log"
    pwsh_zip="$work_dir/PowerShell-7.4.11-win-x64.zip"
    pwsh_zip_url="https://github.com/PowerShell/PowerShell/releases/download/v7.4.11/PowerShell-7.4.11-win-x64.zip"
    pwsh_zip_sha256="558c4115cc6b96cc6a67d74bee40012cf8d38767537f8d2857dc3fa30a63cc63"
    pwsh_dir="$wine_prefix/drive_c/Program Files/PowerShell/7"

    probe_cfw_pwsh() {{
      probe_context="$1"
      : > "$pwsh_probe_log"
      echo "[cage] Probing Chocolatey-for-wine PowerShell ($probe_context)..."
      set +e
      timeout 120s wine "$pwsh_exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command 'Write-Host "[cage] pwsh probe OK"; $PSVersionTable.PSVersion.ToString()' > "$pwsh_probe_log" 2>&1
      pwsh_probe_rc="$?"
      set -e
      if [ -s "$pwsh_probe_log" ]; then
        sed 's/^/[cfw-pwsh] /' "$pwsh_probe_log"
      fi
      if [ "$pwsh_probe_rc" -ne 0 ]; then
        echo "[cage] Chocolatey-for-wine PowerShell probe failed with exit code $pwsh_probe_rc ($probe_context)"
        return "$pwsh_probe_rc"
      fi
      if [ ! -s "$pwsh_probe_log" ]; then
        echo "[cage] PowerShell probe produced no output ($probe_context): $pwsh_exe"
        return 98
      fi
      return 0
    }}

    if ! probe_cfw_pwsh "after Chocolatey-for-wine"; then
      echo "[cage] Repairing Chocolatey-for-wine PowerShell from ZIP payload..."
      set +e
      (
        set -eu
        echo "[cage] Downloading PowerShell 7.4.11 ZIP repair payload..."
        timeout "${{CAGE_CHOCOLATEY_PWSH_REPAIR_TIMEOUT:-1200s}}" curl -fL --retry 3 -o "$pwsh_zip" "$pwsh_zip_url"
        actual_pwsh_zip_sha="$(sha256sum "$pwsh_zip" | cut -d ' ' -f 1)"
        if [ "$actual_pwsh_zip_sha" != "$pwsh_zip_sha256" ]; then
          echo "[cage] ERROR: PowerShell ZIP checksum mismatch"
          echo "[cage]   expected: $pwsh_zip_sha256"
          echo "[cage]   actual:   $actual_pwsh_zip_sha"
          exit 1
        fi
        echo "[cage] Extracting PowerShell ZIP to $pwsh_dir..."
        rm -rf "$pwsh_dir"
        mkdir -p "$pwsh_dir"
        python3 - "$pwsh_zip" "$pwsh_dir" <<'PY'
import sys
import zipfile
archive, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(archive) as zf:
    zf.extractall(dest)
PY
        test -f "$pwsh_exe"
      ) > "$pwsh_zip_repair_log" 2>&1
      pwsh_zip_repair_rc="$?"
      set -e
      if [ -s "$pwsh_zip_repair_log" ]; then
        sed 's/^/[cfw-pwsh-zip] /' "$pwsh_zip_repair_log"
      else
        echo "[cage] PowerShell ZIP repair log was empty"
      fi
      if [ "$pwsh_zip_repair_rc" -ne 0 ]; then
        echo "[cage] ERROR: PowerShell ZIP repair failed with exit code $pwsh_zip_repair_rc"
        exit "$pwsh_zip_repair_rc"
      fi
      echo "[cage] Re-applying Wine Windows version to win10 after PowerShell ZIP repair..."
      timeout "${{CAGE_WINECFG_TIMEOUT:-120s}}" winecfg /v win10
      if ! probe_cfw_pwsh "after PowerShell ZIP repair"; then
        echo "[cage] ERROR: PowerShell ZIP repair failed; pwsh probe still did not produce usable output"
        exit 1
      fi
    fi

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
  fi

  if [ ! -f "$choco_exe" ]; then
    echo "[cage] ERROR: Chocolatey-for-wine finished but choco.exe is missing: $choco_exe"
    echo "[cage] Raw Chocolatey extraction marker: $raw_choco_exe"
    find "$wine_prefix/drive_c/ProgramData" -maxdepth 4 -iname '*choco*' 2>/dev/null | sort || true
    exit 1
  fi

  echo "[cage] Verifying Chocolatey..."
  timeout 120s wine "$choco_exe" --version
  rm -rf "$work_dir"
  echo "[cage] Chocolatey-for-wine installation complete"
else
  echo "[cage] Chocolatey already installed: {choco_exe}"
fi'''
        ]

        package_commands = [
            f'''set -eu
export WINEDLLOVERRIDES=""
choco_exe="{choco_exe}"
if [ ! -f "$choco_exe" ]; then
  echo "[cage] ERROR: choco.exe is missing before package install: $choco_exe"
  exit 1
fi
echo "[cage] Installing Chocolatey packages: {package_args}"
wine "$choco_exe" install {package_args} -y{source_arg}'''
        ]

        return [
            BuildStep(
                commands=install_commands,
                description="Install Chocolatey-for-wine",
            ),
            BuildStep(
                commands=package_commands,
                description=f"Install Chocolatey packages: {package_args}",
            ),
        ]

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
