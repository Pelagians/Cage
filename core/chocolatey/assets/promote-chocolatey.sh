set -eu
echo "[cage] Promote Chocolatey natively"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
choco_exe="${WINEPREFIX:-$HOME/.wine}/drive_c/ProgramData/chocolatey/bin/choco.exe"
raw_choco_exe="${WINEPREFIX:-$HOME/.wine}/drive_c/ProgramData/tools/ChocolateyInstall/choco.exe"
raw_choco_dir="$wine_prefix/drive_c/ProgramData/tools/ChocolateyInstall"
canonical_choco_dir="$wine_prefix/drive_c/ProgramData/chocolatey"
canonical_bin_dir="$canonical_choco_dir/bin"
tools_dir="$wine_prefix/drive_c/tools"
choco_dir_win='C:\ProgramData\chocolatey'
choco_tools_win='C:\tools'
choco_exe_win='C:\ProgramData\chocolatey\bin\choco.exe'

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
    raise SystemExit(f"missing raw Chocolatey source directory: {source}")
if not (source / "choco.exe").is_file():
    raise SystemExit(f"missing raw Chocolatey choco.exe: {source / 'choco.exe'}")
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
    raise SystemExit(f"missing root Chocolatey choco.exe: {root_choco}")
shutil.copy2(root_choco, choco)
if choco.stat().st_size != root_choco.stat().st_size:
    raise SystemExit(f"canonical bin choco.exe size mismatch: {choco} != {root_choco}")
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
native_loader_mscoreei="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/mscoreei.dll"
native_loader_clr="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"
native_loader_clrjit="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clrjit.dll"
native_loader_ucrtbase="$wine_prefix/drive_c/windows/system32/ucrtbase_clr0400.dll"
native_loader_vcruntime="$wine_prefix/drive_c/windows/system32/vcruntime140_clr0400.dll"
for native_loader in "$native_loader_mscoree" "$native_loader_mscoreei" "$native_loader_clr" "$native_loader_clrjit" "$native_loader_ucrtbase" "$native_loader_vcruntime"; do
  if [ ! -f "$native_loader" ]; then
    echo "[cage] ERROR: native CLR loader dependency missing before Chocolatey verification: $native_loader"
    exit 68
  fi
done
# Wine reports "mscoree.dll not found" for IL-only executables when loading
# mscoree or its native dependency closure fails. Keep the upstream-derived
# native CLR loader closure app-local beside canonical choco.exe so IL-only
# import resolution does not depend on Wine's system DLL search path.
cp -f "$native_loader_mscoree" "$canonical_bin_dir/mscoree.dll"
cp -f "$native_loader_mscoreei" "$canonical_bin_dir/mscoreei.dll"
cp -f "$native_loader_clr" "$canonical_bin_dir/clr.dll"
cp -f "$native_loader_clrjit" "$canonical_bin_dir/clrjit.dll"
cp -f "$native_loader_ucrtbase" "$canonical_bin_dir/ucrtbase_clr0400.dll"
cp -f "$native_loader_vcruntime" "$canonical_bin_dir/vcruntime140_clr0400.dll"
echo "[cage] App-local native CLR loader closure copied beside canonical choco.exe"

echo "[cage] Native Chocolatey promotion copied raw payload to canonical directory"
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Environment' /v ChocolateyInstall /t REG_SZ /d "$choco_dir_win" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Environment' /v ChocolateyToolsLocation /t REG_SZ /d "$choco_tools_win" /f
export ChocolateyInstall="$choco_dir_win"
export ChocolateyToolsLocation="$choco_tools_win"
unset WINEDLLOVERRIDES

verify_log="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/chocolatey-verify.log"
mkdir -p "$(dirname "$verify_log")"
echo "[cage] Verifying canonical Chocolatey..."
set +e
timeout "${CAGE_CHOCOLATEY_VERIFY_TIMEOUT:-120s}" wine "$choco_exe_win" --version > "$verify_log" 2>&1
verify_rc="$?"
set -e
if [ "$verify_rc" -ne 0 ]; then
  echo "[cage] WARNING: canonical Chocolatey verification failed rc=$verify_rc; see $verify_log"
  echo "[cage] Continuing to diagnostic step for structured evidence"
  tail -80 "$verify_log" || true
else
  cat "$verify_log"
fi
echo "[cage] Chocolatey native promotion complete"
