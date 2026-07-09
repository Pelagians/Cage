"""Chocolatey package manager module for Wine environments.

Cage treats PietJankbal's Chocolatey-for-wine as the upstream compatibility
boundary. The module pins and verifies the upstream release archive, runs the
upstream ``ChoCinstaller_*.exe`` with noninteractive flags, then adds Cage's
bounded logging, diagnostics, and package-install gate around that installer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

from .base import ModuleBase, ModuleError
from ..build_step import BuildStep

DEFAULT_CHOCOLATEY_FOR_WINE_VERSION = "v0.5c.755"
DEFAULT_CHOCOLATEY_FOR_WINE_SHA256 = "87f4ecc08a9b22f16aa5633ca107c151ddf3fed0b256fed9fb99680af7095d14"


def _sh_single_quote(value: str) -> str:
    """Quote a value for POSIX shell single-quoted context."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


@dataclass
class ChocolateyModule(ModuleBase):
    """Install Chocolatey packages through upstream Chocolatey-for-wine."""

    type: str = "chocolatey"
    install: dict[str, Any] | None = None
    source: str | None = None
    version: str = DEFAULT_CHOCOLATEY_FOR_WINE_VERSION
    sha256: str | None = None

    def capabilities(self) -> dict[str, str]:
        """Return PowerShell-related capability slots claimed by Chocolatey."""
        return {
            "engine": "chocolatey-for-wine-upstream",
            "winps-shim": "chocolatey-for-wine-upstream",
            "shim-library": "chocolatey-for-wine",
        }

    def build(self) -> list[BuildStep]:
        """Generate upstream Chocolatey-for-wine setup and package install steps."""
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
        package_args = " ".join(packages)
        source_arg = f" -s {_sh_single_quote(self.source)}" if self.source else ""

        return [
            self._upstream_installer_step(wine_prefix, choco_exe),
            self._diagnostic_step(wine_prefix, choco_exe),
            self._package_install_step(choco_exe, package_args, source_arg),
        ]

    def _upstream_installer_step(self, wine_prefix: str, choco_exe: str) -> BuildStep:
        release_url = (
            "https://github.com/PietJankbal/Chocolatey-for-wine/releases/download/"
            f"{self.version}/Chocolatey-for-wine.7z"
        )
        expected_cfw_sha = self.sha256
        if expected_cfw_sha is None and self.version == DEFAULT_CHOCOLATEY_FOR_WINE_VERSION:
            expected_cfw_sha = DEFAULT_CHOCOLATEY_FOR_WINE_SHA256
        expected_cfw_sha = expected_cfw_sha or ""

        script = r'''set -eu
unset WINEDLLOVERRIDES
echo "[cage] Install Chocolatey-for-wine through upstream ChoCinstaller"
wine_prefix="__WINE_PREFIX__"
choco_exe="__CHOCO_EXE__"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
cfw_cache="$module_cache/chocolatey-for-wine/__VERSION__"
cfw_archive="$cfw_cache/Chocolatey-for-wine.7z"
cfw_extract="$cfw_cache/extracted/Chocolatey-for-wine"
cfw_archive_url="__RELEASE_URL__"
cfw_archive_sha256="__SHA256__"
logs_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs"
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
installer_log="$logs_dir/chocolatey-upstream-installer.log"
verify_log="$logs_dir/chocolatey-verify.log"
upstream_status_json="$metadata_dir/chocolatey-upstream-installer.json"

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
try:
    import py7zr
except Exception as exc:  # pragma: no cover - runs in generated build script
    raise SystemExit(f"7z/7zz/7za or Python py7zr is required to extract {sys.argv[1]}: {exc}")
archive, dest = sys.argv[1], sys.argv[2]
with py7zr.SevenZipFile(archive, mode="r") as zf:
    zf.extractall(dest)
PY
  fi
}

mkdir -p "$cfw_cache" "$logs_dir" "$metadata_dir"
if [ ! -f "$cfw_archive" ]; then
  echo "[cage] Downloading Chocolatey-for-wine __VERSION__..."
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
if [ ! -d "$cfw_extract" ] || ! find "$cfw_extract" -maxdepth 1 -type f -name 'ChoCinstaller_*.exe' | grep -q .; then
  rm -rf "$cfw_cache/extracted"
  mkdir -p "$cfw_cache/extracted"
  echo "[cage] Extracting Chocolatey-for-wine release archive..."
  extract_7z_archive "$cfw_archive" "$cfw_cache/extracted"
fi

cfw_installer="$(find "$cfw_extract" -maxdepth 1 -type f -name 'ChoCinstaller_*.exe' | sort | head -n 1)"
if [ -z "$cfw_installer" ]; then
  echo "[cage] ERROR: Chocolatey-for-wine release did not contain ChoCinstaller_*.exe"
  find "$cfw_cache/extracted" -maxdepth 3 -type f | sort || true
  exit 1
fi
cfw_installer_win="$(winepath -w "$cfw_installer")"
cfw_cache_win="$(winepath -w "$cfw_cache")"
export CFW_CACHE="$cfw_cache_win"

echo "[cage] Running upstream Chocolatey-for-wine installer: $cfw_installer_win /s /q"
echo "[cage] CFW_CACHE=$CFW_CACHE"
rm -f "$installer_log" "$verify_log"
set +e
timeout "${CAGE_CHOCOLATEY_UPSTREAM_TIMEOUT:-3600s}" wine "$cfw_installer" /s /q > "$installer_log" 2>&1
installer_rc="$?"
set -e
if [ -f "$installer_log" ]; then
  echo "[cage] Upstream Chocolatey-for-wine installer log tail:"
  tail -160 "$installer_log" | sed 's/^/[chocolatey-upstream] /' || true
fi
if [ "$installer_rc" -ne 0 ]; then
  echo "[cage] WARNING: upstream Chocolatey-for-wine installer exited rc=$installer_rc; verifying installed state before failing"
fi

export ChocolateyInstall='C:\ProgramData\chocolatey'
export ChocolateyToolsLocation='C:\tools'
export WINEDLLOVERRIDES='mscoree=n'
if [ -f "$choco_exe" ]; then
  set +e
  timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" --version > "$verify_log" 2>&1
  verify_rc="$?"
  set -e
else
  verify_rc="127"
  : > "$verify_log"
fi
python3 - "$upstream_status_json" "$cfw_installer" "$installer_rc" "$choco_exe" "$verify_rc" <<'PY'
import json
import sys
from pathlib import Path
status_json, installer, installer_rc, choco_exe, verify_rc = sys.argv[1:]
payload = {
    "schemaVersion": "cage.chocolatey-upstream-installer/v0",
    "installer": installer,
    "installerExitCode": int(installer_rc),
    "choco": choco_exe,
    "chocoExists": Path(choco_exe).is_file(),
    "chocoVersionExitCode": int(verify_rc),
    "logs": {
        "installer": "logs/chocolatey-upstream-installer.log",
        "verify": "logs/chocolatey-verify.log",
    },
}
Path(status_json).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
if [ ! -f "$choco_exe" ]; then
  echo "[cage] ERROR: upstream Chocolatey-for-wine installer did not create canonical choco.exe: $choco_exe"
  find "$wine_prefix/drive_c/ProgramData" -maxdepth 5 -iname '*choco*' 2>/dev/null | sort || true
  exit 68
fi
if [ "$verify_rc" -ne 0 ]; then
  echo "[cage] WARNING: canonical Chocolatey verification failed rc=$verify_rc; see $verify_log"
  echo "[cage] Continuing to diagnostic step for structured evidence"
  tail -120 "$verify_log" || true
else
  cat "$verify_log"
fi
echo "[cage] Upstream Chocolatey-for-wine install step complete"'''
        script = (
            script.replace("__WINE_PREFIX__", wine_prefix)
            .replace("__CHOCO_EXE__", choco_exe)
            .replace("__VERSION__", self.version)
            .replace("__RELEASE_URL__", release_url)
            .replace("__SHA256__", expected_cfw_sha)
        )
        return BuildStep(
            commands=[script],
            description="Install Chocolatey-for-wine via upstream ChoCinstaller",
            kind="wine-run",
            timeout=3600,
        )

    def _diagnostic_step(self, wine_prefix: str, choco_exe: str) -> BuildStep:
        script = r'''set -eu
echo "[cage] Diagnose Chocolatey readiness"
wine_prefix="__WINE_PREFIX__"
choco_exe="__CHOCO_EXE__"
canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"
canonical_bin_dir="$canonical_choco_dir/bin"
native_mscoree="$wine_prefix/drive_c/windows/system32/mscoree.dll"
native_mscoreei="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/mscoreei.dll"
native_clr="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"
export ChocolateyInstall='C:\ProgramData\chocolatey'
export ChocolateyToolsLocation='C:\tools'
export WINEDLLOVERRIDES='mscoree=n'
probe_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-diagnostics"
diagnostic_json="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-diagnostic.json"
upstream_status_json="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-upstream-installer.json"
mkdir -p "$probe_dir" "$(dirname "$diagnostic_json")"

set +e
test -f "$upstream_status_json"
upstream_status_rc="$?"
winepath -w "$choco_exe" > "$probe_dir/winepath-canonical.log" 2>&1
winepath_rc="$?"
wine cmd /c dir 'C:\ProgramData\chocolatey\bin' > "$probe_dir/cmd-dir-chocolatey-bin.log" 2>&1
cmd_dir_rc="$?"
wine cmd /c echo CAGE-CMD-OK > "$probe_dir/cmd-echo.log" 2>&1
cmd_echo_rc="$?"
wine reg query 'HKCU\Environment' /v ChocolateyInstall > "$probe_dir/registry-chocolatey-install.log" 2>&1
registry_install_rc="$?"
wine reg query 'HKCU\Environment' /v ChocolateyToolsLocation > "$probe_dir/registry-chocolatey-tools.log" 2>&1
registry_tools_rc="$?"
wine reg query 'HKCU\Software\Wine\DllOverrides' /v mscoree > "$probe_dir/registry-wine-mscoree.log" 2>&1
wine_dll_mscoree_rc="$?"
wine reg query 'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full' /v Release > "$probe_dir/registry-dotnet48-release.log" 2>&1
dotnet_release_rc="$?"
test -f "$native_mscoree"
native_mscoree_rc="$?"
test -f "$native_mscoreei"
native_mscoreei_rc="$?"
test -f "$native_clr"
native_clr_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" --version > "$probe_dir/choco-version.log" 2>&1
choco_version_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine cmd /c 'C:\ProgramData\chocolatey\bin\choco.exe --version' > "$probe_dir/choco-version-cmd.log" 2>&1
choco_version_cmd_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe" source list > "$probe_dir/choco-source-list.log" 2>&1
choco_source_rc="$?"
WINEDEBUG=+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe" --version > "$probe_dir/choco-mscoree-loader.log" 2>&1
choco_loader_rc="$?"
if [ "$choco_version_rc" -ne 0 ] && [ ! -s "$probe_dir/choco-version.log" ]; then
  WINEDEBUG=+seh,+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe" --version > "$probe_dir/choco-version-winedebug.log" 2>&1 || true
fi
find "$canonical_choco_dir" -maxdepth 3 -type f | sort > "$probe_dir/promoted-files.log" 2>&1 || true
set -e

python3 - "$diagnostic_json" "$upstream_status_json" "$upstream_status_rc" "$choco_exe" "$canonical_choco_dir" "$native_mscoree" "$native_mscoreei" "$native_clr" "$winepath_rc" "$cmd_dir_rc" "$cmd_echo_rc" "$registry_install_rc" "$registry_tools_rc" "$wine_dll_mscoree_rc" "$dotnet_release_rc" "$native_mscoree_rc" "$native_mscoreei_rc" "$native_clr_rc" "$choco_version_rc" "$choco_version_cmd_rc" "$choco_source_rc" "$choco_loader_rc" <<'PY'
import json
import sys
from pathlib import Path

(
    diagnostic_json,
    upstream_status_json,
    upstream_status_rc,
    choco_exe,
    canonical_choco_dir,
    native_mscoree,
    native_mscoreei,
    native_clr,
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
    choco_version_rc,
    choco_version_cmd_rc,
    choco_source_rc,
    choco_loader_rc,
) = sys.argv[1:]
canonical = Path(choco_exe)
canonical_dir = Path(canonical_choco_dir)
upstream_status = {}
status_path = Path(upstream_status_json)
if status_path.is_file():
    try:
        upstream_status = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        upstream_status = {}
checks = {
    "upstreamInstaller": upstream_status_rc == "0" and upstream_status.get("chocoExists") is True,
    "canonicalChocoExists": canonical.is_file(),
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
    "upstreamStatus": upstream_status,
    "paths": {
        "canonicalChoco": choco_exe,
        "nativeMscoree": native_mscoree,
        "nativeMscoreei": native_mscoreei,
        "nativeClr": native_clr,
        "logDirectory": "logs/chocolatey-diagnostics",
        "upstreamInstallerStatus": "metadata/chocolatey-upstream-installer.json",
    },
    "logs": {
        "upstreamInstaller": "logs/chocolatey-upstream-installer.log",
        "chocoVersion": "logs/chocolatey-diagnostics/choco-version.log",
        "chocoVersionViaCmd": "logs/chocolatey-diagnostics/choco-version-cmd.log",
        "chocoVersionWineDebug": "logs/chocolatey-diagnostics/choco-version-winedebug.log",
        "chocoMscoreeLoader": "logs/chocolatey-diagnostics/choco-mscoree-loader.log",
        "wineDllOverridesMscoree": "logs/chocolatey-diagnostics/registry-wine-mscoree.log",
        "dotnetReleaseRegistry": "logs/chocolatey-diagnostics/registry-dotnet48-release.log",
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
  echo "[cage] Chocolatey mscoree loader tail:"
  tail -120 "$probe_dir/choco-mscoree-loader.log" || true
  if [ -f "$probe_dir/choco-version-winedebug.log" ]; then
    echo "[cage] Chocolatey WINEDEBUG tail:"
    tail -120 "$probe_dir/choco-version-winedebug.log" || true
  fi
  exit 69
fi
echo "[cage] Chocolatey diagnostics passed"'''
        script = script.replace("__WINE_PREFIX__", wine_prefix).replace("__CHOCO_EXE__", choco_exe)
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
