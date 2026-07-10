set -eu
echo "[cage] Diagnose Chocolatey readiness"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
choco_exe="$wine_prefix/drive_c/ProgramData/chocolatey/bin/choco.exe"
raw_choco_exe="$wine_prefix/drive_c/ProgramData/tools/ChocolateyInstall/choco.exe"
choco_exe_win='C:\ProgramData\chocolatey\bin\choco.exe'
canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"
canonical_root_choco="$canonical_choco_dir/choco.exe"
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
test -f "$choco_exe"; canonical_choco_rc="$?"
test -f "$canonical_root_choco"; canonical_root_rc="$?"
cmp -s "$choco_exe" "$canonical_root_choco"; canonical_match_rc="$?"
test -f "$raw_choco_exe"; raw_choco_rc="$?"
test -f "$canonical_choco_dir/redirects/choco.exe"; redirect_rc="$?"
winepath -w "$choco_exe" > "$probe_dir/winepath-canonical.log" 2>&1; winepath_rc="$?"
wine cmd /c dir 'C:\ProgramData\chocolatey\bin' > "$probe_dir/cmd-dir-chocolatey-bin.log" 2>&1; cmd_dir_rc="$?"
wine cmd /c echo CAGE-CMD-OK > "$probe_dir/cmd-echo.log" 2>&1; cmd_echo_rc="$?"
wine reg query 'HKCU\Environment' /v ChocolateyInstall > "$probe_dir/registry-chocolatey-install.log" 2>&1; registry_install_rc="$?"
wine reg query 'HKCU\Environment' /v ChocolateyToolsLocation > "$probe_dir/registry-chocolatey-tools.log" 2>&1; registry_tools_rc="$?"
wine reg query 'HKCU\Software\Wine\DllOverrides' /v mscoree > "$probe_dir/registry-wine-mscoree.log" 2>&1; wine_dll_mscoree_rc="$?"
grep -Eiq 'mscoree[[:space:]]+REG_SZ[[:space:]]+native[[:space:]]*$' "$probe_dir/registry-wine-mscoree.log"; wine_dll_mscoree_policy_rc="$?"
wine reg query 'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full' /v Release > "$probe_dir/registry-dotnet48-release.log" 2>&1; dotnet_release_rc="$?"
test -f "$native_mscoree"; native_mscoree_rc="$?"
test -f "$native_mscoreei"; native_mscoreei_rc="$?"
test -f "$native_clr"; native_clr_rc="$?"
test -f "$native_clrjit"; native_clrjit_rc="$?"
test -f "$native_wow64_mscoree"; native_wow64_mscoree_rc="$?"
test -f "$native_wow64_mscoreei"; native_wow64_mscoreei_rc="$?"
test -f "$native_wow64_clr"; native_wow64_clr_rc="$?"
test -f "$native_ucrtbase"; native_ucrtbase_rc="$?"
test -f "$native_vcruntime"; native_vcruntime_rc="$?"
test -f "$app_local_mscoree"; app_local_mscoree_rc="$?"
test -f "$app_local_mscoreei"; app_local_mscoreei_rc="$?"
test -f "$app_local_clr"; app_local_clr_rc="$?"
test -f "$app_local_clrjit"; app_local_clrjit_rc="$?"
test -f "$app_local_ucrtbase"; app_local_ucrtbase_rc="$?"
test -f "$app_local_vcruntime"; app_local_vcruntime_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-45s}" wine "$choco_exe_win" --version > "$probe_dir/choco-version.log" 2>&1; choco_version_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-45s}" wine cmd /c 'C:\ProgramData\chocolatey\bin\choco.exe --version' > "$probe_dir/choco-version-cmd.log" 2>&1; choco_version_cmd_rc="$?"
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-45s}" wine "$choco_exe_win" source list > "$probe_dir/choco-source-list.log" 2>&1; choco_source_rc="$?"
set -e

python3 - "$diagnostic_json" "$choco_exe" "$raw_choco_exe" "$canonical_choco_dir" "$native_mscoree" "$native_mscoreei" "$native_clr" "$native_clrjit" "$native_wow64_mscoree" "$native_wow64_mscoreei" "$native_wow64_clr" "$native_ucrtbase" "$native_vcruntime" "$app_local_mscoree" "$app_local_mscoreei" "$app_local_clr" "$app_local_clrjit" "$app_local_ucrtbase" "$app_local_vcruntime" "$canonical_choco_rc" "$canonical_root_rc" "$canonical_match_rc" "$raw_choco_rc" "$redirect_rc" "$winepath_rc" "$cmd_dir_rc" "$cmd_echo_rc" "$registry_install_rc" "$registry_tools_rc" "$wine_dll_mscoree_rc" "$wine_dll_mscoree_policy_rc" "$dotnet_release_rc" "$native_mscoree_rc" "$native_mscoreei_rc" "$native_clr_rc" "$native_clrjit_rc" "$native_wow64_mscoree_rc" "$native_wow64_mscoreei_rc" "$native_wow64_clr_rc" "$native_ucrtbase_rc" "$native_vcruntime_rc" "$app_local_mscoree_rc" "$app_local_mscoreei_rc" "$app_local_clr_rc" "$app_local_clrjit_rc" "$app_local_ucrtbase_rc" "$app_local_vcruntime_rc" "$choco_version_rc" "$choco_version_cmd_rc" "$choco_source_rc" <<'PY'
import json
import sys
from pathlib import Path
(
    diagnostic_json, choco_exe, raw_choco_exe, canonical_choco_dir,
    native_mscoree, native_mscoreei, native_clr, native_clrjit,
    native_wow64_mscoree, native_wow64_mscoreei, native_wow64_clr,
    native_ucrtbase, native_vcruntime, app_local_mscoree, app_local_mscoreei,
    app_local_clr, app_local_clrjit, app_local_ucrtbase, app_local_vcruntime,
    canonical_choco_rc, canonical_root_rc, canonical_match_rc, raw_choco_rc,
    redirect_rc, winepath_rc, cmd_dir_rc, cmd_echo_rc, registry_install_rc,
    registry_tools_rc, wine_dll_mscoree_rc, wine_dll_mscoree_policy_rc,
    dotnet_release_rc, native_mscoree_rc, native_mscoreei_rc, native_clr_rc,
    native_clrjit_rc, native_wow64_mscoree_rc, native_wow64_mscoreei_rc,
    native_wow64_clr_rc, native_ucrtbase_rc, native_vcruntime_rc,
    app_local_mscoree_rc, app_local_mscoreei_rc, app_local_clr_rc,
    app_local_clrjit_rc, app_local_ucrtbase_rc, app_local_vcruntime_rc,
    choco_version_rc, choco_version_cmd_rc, choco_source_rc,
) = sys.argv[1:]
canonical = Path(choco_exe)
raw = Path(raw_choco_exe)
canonical_dir = Path(canonical_choco_dir)
root_choco = canonical_dir / "choco.exe"
redirect_choco = canonical_dir / "redirects" / "choco.exe"

def ok(value):
    return value == "0"

def file_size(path):
    candidate = Path(path)
    return candidate.stat().st_size if candidate.is_file() else None

required = {
    "canonicalChocoExists": ok(canonical_choco_rc) and canonical.is_file(),
    "canonicalChocoMatchesNupkgExecutable": ok(canonical_root_rc) and ok(canonical_match_rc),
    "registryEnvironment": ok(registry_install_rc) and ok(registry_tools_rc),
    "wineDllOverridesMscoree": ok(wine_dll_mscoree_rc),
    "wineDllOverridesMscoreeNative": ok(wine_dll_mscoree_policy_rc),
    "dotnetReleaseRegistry": ok(dotnet_release_rc),
    "nativeMscoreeExists": ok(native_mscoree_rc) and Path(native_mscoree).is_file(),
    "nativeMscoreeiExists": ok(native_mscoreei_rc) and Path(native_mscoreei).is_file(),
    "nativeClrExists": ok(native_clr_rc) and Path(native_clr).is_file(),
    "nativeClrjitExists": ok(native_clrjit_rc) and Path(native_clrjit).is_file(),
    "nativeWow64MscoreeExists": ok(native_wow64_mscoree_rc) and Path(native_wow64_mscoree).is_file(),
    "nativeWow64MscoreeiExists": ok(native_wow64_mscoreei_rc) and Path(native_wow64_mscoreei).is_file(),
    "nativeWow64ClrExists": ok(native_wow64_clr_rc) and Path(native_wow64_clr).is_file(),
    "nativeUcrtbaseClrExists": ok(native_ucrtbase_rc) and Path(native_ucrtbase).is_file(),
    "nativeVcruntimeClrExists": ok(native_vcruntime_rc) and Path(native_vcruntime).is_file(),
    "appLocalMscoreeExists": ok(app_local_mscoree_rc) and Path(app_local_mscoree).is_file(),
    "appLocalMscoreeiExists": ok(app_local_mscoreei_rc) and Path(app_local_mscoreei).is_file(),
    "appLocalClrExists": ok(app_local_clr_rc) and Path(app_local_clr).is_file(),
    "appLocalClrjitExists": ok(app_local_clrjit_rc) and Path(app_local_clrjit).is_file(),
    "appLocalUcrtbaseClrExists": ok(app_local_ucrtbase_rc) and Path(app_local_ucrtbase).is_file(),
    "appLocalVcruntimeClrExists": ok(app_local_vcruntime_rc) and Path(app_local_vcruntime).is_file(),
    "chocoVersion": ok(choco_version_rc),
    "sourceList": ok(choco_source_rc),
}
advisory = {
    "rawToolsPayloadExists": ok(raw_choco_rc) and raw.is_file(),
    "redirectExists": ok(redirect_rc) and redirect_choco.is_file(),
    "winepathCanonical": ok(winepath_rc),
    "wineCmdEcho": ok(cmd_echo_rc),
    "cmdDirCanonicalBin": ok(cmd_dir_rc),
    "chocoVersionViaCmd": ok(choco_version_cmd_rc),
}
required_passed = all(required.values())
failed_checks = sorted(name for name, passed in required.items() if not passed)
checks = {**required, **advisory}
payload = {
    "schemaVersion": "cage.chocolatey-diagnostic/v0",
    "phase": "Chocolatey diagnostic",
    "status": "passed" if required_passed else "failed",
    "failedChecks": failed_checks,
    "returnCodes": {
        "chocoVersion": int(choco_version_rc),
        "chocoVersionViaCmd": int(choco_version_cmd_rc),
        "sourceList": int(choco_source_rc),
    },
    "checks": checks,
    "tiers": {
        "required": {"status": "passed" if required_passed else "failed", "checks": required},
        "advisory": {"status": "recorded", "checks": advisory},
        "failureOnly": {"status": "not-run", "checks": {}},
    },
    "paths": {
        "canonicalChoco": choco_exe,
        "rawToolsPayload": raw_choco_exe,
        "logDirectory": "logs/chocolatey-diagnostics",
    },
    "fileSizes": {
        "canonicalChoco": file_size(canonical),
        "rootChoco": file_size(root_choco),
        "redirectChoco": file_size(redirect_choco),
        "rawToolsPayload": file_size(raw),
        "nativeMscoree": file_size(native_mscoree),
        "nativeMscoreei": file_size(native_mscoreei),
        "nativeClr": file_size(native_clr),
        "nativeClrjit": file_size(native_clrjit),
        "nativeUcrtbaseClr": file_size(native_ucrtbase),
        "nativeVcruntimeClr": file_size(native_vcruntime),
        "appLocalMscoree": file_size(app_local_mscoree),
        "appLocalMscoreei": file_size(app_local_mscoreei),
        "appLocalClr": file_size(app_local_clr),
        "appLocalClrjit": file_size(app_local_clrjit),
        "appLocalUcrtbaseClr": file_size(app_local_ucrtbase),
        "appLocalVcruntimeClr": file_size(app_local_vcruntime),
    },
    "logs": {
        "chocoVersion": "logs/chocolatey-diagnostics/choco-version.log",
        "chocoVersionViaCmd": "logs/chocolatey-diagnostics/choco-version-cmd.log",
        "wineDllOverridesMscoree": "logs/chocolatey-diagnostics/registry-wine-mscoree.log",
        "dotnetReleaseRegistry": "logs/chocolatey-diagnostics/registry-dotnet48-release.log",
        "chocoVersionWineDebug": "logs/chocolatey-diagnostics/choco-version-winedebug.log",
        "chocoMscoreeLoader": "logs/chocolatey-diagnostics/choco-mscoree-loader.log",
        "promotedFiles": "logs/chocolatey-diagnostics/promoted-files.log",
    },
}
path = Path(diagnostic_json)
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY

required_status="$(python3 - "$diagnostic_json" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["tiers"]["required"]["status"])
PY
)"
if [ "$required_status" != "passed" ]; then
  echo "[cage] Required Chocolatey checks failed; collecting failure-only diagnostics"
  cage_chocolatey_collect_failure_diagnostics "$diagnostic_json" "readiness"
  echo "[cage] ERROR: Chocolatey required diagnostics failed; see $diagnostic_json"
  tail -80 "$probe_dir/choco-version.log" || true
  tail -120 "$probe_dir/choco-mscoree-loader.log" || true
  exit 69
fi
echo "[cage] Chocolatey required diagnostics passed"
