set -eu
echo "[cage] Diagnose Chocolatey readiness"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
choco_exe="${WINEPREFIX:-$HOME/.wine}/drive_c/ProgramData/chocolatey/bin/choco.exe"
raw_choco_exe="${WINEPREFIX:-$HOME/.wine}/drive_c/ProgramData/tools/ChocolateyInstall/choco.exe"
choco_exe_win='C:\ProgramData\chocolatey\bin\choco.exe'
canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"
canonical_bin_dir="$canonical_choco_dir/bin"
native_mscoree="$wine_prefix/drive_c/windows/system32/mscoree.dll"
native_mscoreei="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/mscoreei.dll"
native_clr="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"
native_clrjit="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clrjit.dll"
native_wow64_mscoree="$wine_prefix/drive_c/windows/syswow64/mscoree.dll"
native_wow64_mscoreei="$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/mscoreei.dll"
native_wow64_clr="$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/clr.dll"
native_ucrtbase="$wine_prefix/drive_c/windows/system32/ucrtbase_clr0400.dll"
native_vcruntime="$wine_prefix/drive_c/windows/system32/vcruntime140_clr0400.dll"
app_local_mscoree="$canonical_bin_dir/mscoree.dll"
app_local_mscoreei="$canonical_bin_dir/mscoreei.dll"
app_local_clr="$canonical_bin_dir/clr.dll"
app_local_clrjit="$canonical_bin_dir/clrjit.dll"
app_local_ucrtbase="$canonical_bin_dir/ucrtbase_clr0400.dll"
app_local_vcruntime="$canonical_bin_dir/vcruntime140_clr0400.dll"
export ChocolateyInstall='C:\ProgramData\chocolatey'
export ChocolateyToolsLocation='C:\tools'
unset WINEDLLOVERRIDES
probe_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-diagnostics"
diagnostic_json="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-diagnostic.json"
mkdir -p "$probe_dir" "$(dirname "$diagnostic_json")"

set +e
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
grep -Eiq 'mscoree[[:space:]]+REG_SZ[[:space:]]+native[[:space:]]*$' "$probe_dir/registry-wine-mscoree.log"
wine_dll_mscoree_policy_rc="$?"
wine reg query 'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full' /v Release > "$probe_dir/registry-dotnet48-release.log" 2>&1
dotnet_release_rc="$?"
test -f "$native_mscoree"
native_mscoree_rc="$?"
test -f "$native_mscoreei"
native_mscoreei_rc="$?"
test -f "$native_clr"
native_clr_rc="$?"
test -f "$native_clrjit"
native_clrjit_rc="$?"
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
test -f "$app_local_mscoreei"
app_local_mscoreei_rc="$?"
test -f "$app_local_clr"
app_local_clr_rc="$?"
test -f "$app_local_clrjit"
app_local_clrjit_rc="$?"
test -f "$app_local_ucrtbase"
app_local_ucrtbase_rc="$?"
test -f "$app_local_vcruntime"
app_local_vcruntime_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" --version > "$probe_dir/choco-version.log" 2>&1
choco_version_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine cmd /c 'C:\ProgramData\chocolatey\bin\choco.exe --version' > "$probe_dir/choco-version-cmd.log" 2>&1
choco_version_cmd_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" source list > "$probe_dir/choco-source-list.log" 2>&1
choco_source_rc="$?"
WINEDEBUG=+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe_win" --version > "$probe_dir/choco-mscoree-loader.log" 2>&1
choco_loader_rc="$?"
if [ "$choco_version_rc" -ne 0 ] && [ ! -s "$probe_dir/choco-version.log" ]; then
  WINEDEBUG=+seh,+loaddll timeout "${CAGE_CHOCOLATEY_DEBUG_TIMEOUT:-60s}" wine "$choco_exe_win" --version > "$probe_dir/choco-version-winedebug.log" 2>&1 || true
fi
python3 - "$canonical_choco_dir" > "$probe_dir/promoted-files.log" 2>&1 <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    print(f"{path.stat().st_size}	{path}")
PY
set -e

python3 - "$diagnostic_json" "$choco_exe" "$raw_choco_exe" "$canonical_choco_dir" "$native_mscoree" "$native_mscoreei" "$native_clr" "$native_clrjit" "$native_wow64_mscoree" "$native_wow64_mscoreei" "$native_wow64_clr" "$native_ucrtbase" "$native_vcruntime" "$app_local_mscoree" "$app_local_mscoreei" "$app_local_clr" "$app_local_clrjit" "$app_local_ucrtbase" "$app_local_vcruntime" "$winepath_rc" "$cmd_dir_rc" "$cmd_echo_rc" "$registry_install_rc" "$registry_tools_rc" "$wine_dll_mscoree_rc" "$wine_dll_mscoree_policy_rc" "$dotnet_release_rc" "$native_mscoree_rc" "$native_mscoreei_rc" "$native_clr_rc" "$native_clrjit_rc" "$native_wow64_mscoree_rc" "$native_wow64_mscoreei_rc" "$native_wow64_clr_rc" "$native_ucrtbase_rc" "$native_vcruntime_rc" "$app_local_mscoree_rc" "$app_local_mscoreei_rc" "$app_local_clr_rc" "$app_local_clrjit_rc" "$app_local_ucrtbase_rc" "$app_local_vcruntime_rc" "$choco_version_rc" "$choco_version_cmd_rc" "$choco_source_rc" "$choco_loader_rc" <<'PY'
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
    native_clrjit,
    native_wow64_mscoree,
    native_wow64_mscoreei,
    native_wow64_clr,
    native_ucrtbase,
    native_vcruntime,
    app_local_mscoree,
    app_local_mscoreei,
    app_local_clr,
    app_local_clrjit,
    app_local_ucrtbase,
    app_local_vcruntime,
    winepath_rc,
    cmd_dir_rc,
    cmd_echo_rc,
    registry_install_rc,
    registry_tools_rc,
    wine_dll_mscoree_rc,
    wine_dll_mscoree_policy_rc,
    dotnet_release_rc,
    native_mscoree_rc,
    native_mscoreei_rc,
    native_clr_rc,
    native_clrjit_rc,
    native_wow64_mscoree_rc,
    native_wow64_mscoreei_rc,
    native_wow64_clr_rc,
    native_ucrtbase_rc,
    native_vcruntime_rc,
    app_local_mscoree_rc,
    app_local_mscoreei_rc,
    app_local_clr_rc,
    app_local_clrjit_rc,
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
app_local_mscoreei_path = Path(app_local_mscoreei)
app_local_clr_path = Path(app_local_clr)
app_local_clrjit_path = Path(app_local_clrjit)
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
    "wineDllOverridesMscoreeNative": wine_dll_mscoree_policy_rc == "0",
    "dotnetReleaseRegistry": dotnet_release_rc == "0",
    "nativeMscoreeExists": native_mscoree_rc == "0" and Path(native_mscoree).is_file(),
    "nativeMscoreeiExists": native_mscoreei_rc == "0" and Path(native_mscoreei).is_file(),
    "nativeClrExists": native_clr_rc == "0" and Path(native_clr).is_file(),
    "nativeClrjitExists": native_clrjit_rc == "0" and Path(native_clrjit).is_file(),
    "nativeWow64MscoreeExists": native_wow64_mscoree_rc == "0" and Path(native_wow64_mscoree).is_file(),
    "nativeWow64MscoreeiExists": native_wow64_mscoreei_rc == "0" and Path(native_wow64_mscoreei).is_file(),
    "nativeWow64ClrExists": native_wow64_clr_rc == "0" and Path(native_wow64_clr).is_file(),
    "nativeUcrtbaseClrExists": native_ucrtbase_rc == "0" and Path(native_ucrtbase).is_file(),
    "nativeVcruntimeClrExists": native_vcruntime_rc == "0" and Path(native_vcruntime).is_file(),
    "appLocalMscoreeExists": app_local_mscoree_rc == "0" and Path(app_local_mscoree).is_file(),
    "appLocalMscoreeiExists": app_local_mscoreei_rc == "0" and Path(app_local_mscoreei).is_file(),
    "appLocalClrExists": app_local_clr_rc == "0" and Path(app_local_clr).is_file(),
    "appLocalClrjitExists": app_local_clrjit_rc == "0" and Path(app_local_clrjit).is_file(),
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
        "nativeClrjit": native_clrjit,
        "nativeWow64Mscoree": native_wow64_mscoree,
        "nativeWow64Mscoreei": native_wow64_mscoreei,
        "nativeWow64Clr": native_wow64_clr,
        "nativeUcrtbaseClr": native_ucrtbase,
        "nativeVcruntimeClr": native_vcruntime,
        "appLocalMscoree": app_local_mscoree,
        "appLocalMscoreei": app_local_mscoreei,
        "appLocalClr": app_local_clr,
        "appLocalClrjit": app_local_clrjit,
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
        "nativeMscoreei": file_size(Path(native_mscoreei)),
        "nativeClr": file_size(Path(native_clr)),
        "nativeClrjit": file_size(Path(native_clrjit)),
        "nativeUcrtbaseClr": file_size(Path(native_ucrtbase)),
        "nativeVcruntimeClr": file_size(Path(native_vcruntime)),
        "appLocalMscoree": file_size(app_local_mscoree_path),
        "appLocalMscoreei": file_size(app_local_mscoreei_path),
        "appLocalClr": file_size(app_local_clr_path),
        "appLocalClrjit": file_size(app_local_clrjit_path),
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
echo "[cage] Chocolatey diagnostics passed"
