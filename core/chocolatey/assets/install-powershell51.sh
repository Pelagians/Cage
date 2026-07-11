set -eu
unset WINEDLLOVERRIDES

wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bundle_root="${CAGE_BUNDLE_MOUNT:-/opt/cage}"
work="$module_cache/windows-powershell-5.1"
archive="$work/Win7AndW2K8R2-KB3191566-x64.zip"
archive_url="https://download.microsoft.com/download/6/F/5/6F5FF66C-6775-42B0-86C4-47D41F2DA187/Win7AndW2K8R2-KB3191566-x64.zip"
archive_sha256="f383c34aa65332662a17d95409a2ddedadceda74427e35d05024cd0a6a2fa647"
extract_root="$work/extracted"
payload_root="$work/payload"
metadata="$bundle_root/metadata/powershell-engine.json"
log_root="$bundle_root/logs/powershell-engine"
backend64="$wine_prefix/drive_c/windows/system32/WindowsPowerShell/v1.0/ps51.exe"
backend32="$wine_prefix/drive_c/windows/syswow64/WindowsPowerShell/v1.0/ps51.exe"
expand_exe="$wine_prefix/drive_c/windows/system32/expand.exe"
probe_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
probe_script="$probe_root/engine-probe.ps1"
probe_marker="$probe_root/engine-probe-ok.txt"

mkdir -p "$work" "$extract_root" "$payload_root" "$log_root" "$probe_root" "$(dirname "$metadata")"

verify_backend() {
  [ -s "$backend64" ] || return 1
  probe_script_win="$(winepath -w "$probe_script")"
  probe_marker_win="$(winepath -w "$probe_marker")"
  backend_log="$log_root/direct-probe.log"
  normalized_log="$log_root/direct-probe.normalized.log"
  rm -f "$probe_marker"
  cat > "$probe_script.part" <<'PS1'
param([Parameter(Mandatory = $true)][string]$MarkerPath)
$ErrorActionPreference = 'Stop'
$version = $PSVersionTable.PSVersion.ToString()
[System.IO.File]::WriteAllText($MarkerPath, $version)
[Console]::Out.WriteLine('[cage] engine-version=' + $version)
PS1
  mv -f "$probe_script.part" "$probe_script"

  set +e
  timeout --kill-after=15s 240s wine "$backend64" \
    -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File "$probe_script_win" "$probe_marker_win" >"$backend_log" 2>&1
  process_rc="$?"
  timeout --kill-after=10s 90s wineserver -w >>"$backend_log" 2>&1
  settle_rc="$?"
  tr -d '\r' < "$backend_log" > "$normalized_log"
  if grep -Eq '^\[cage\] engine-version=5\.1([.]|$)' "$normalized_log"; then
    stdout_rc=0
  else
    stdout_rc=1
  fi
  if [ -s "$probe_marker" ] && grep -Eq '^5\.1([.]|$)' "$probe_marker"; then
    sentinel_rc=0
  else
    sentinel_rc=1
  fi
  set -e
  cat "$normalized_log"

  python3 - "$metadata" "$process_rc" "$settle_rc" "$stdout_rc" "$sentinel_rc" <<'PY'
import json
import sys
from pathlib import Path
output = Path(sys.argv[1])
record = {
    "schemaVersion": "cage.powershell-engine/v1",
    "provider": "windows-powershell-5.1-cfw",
    "source": "Win7AndW2K8R2-KB3191566-x64",
    "returnCodes": {
        "process": int(sys.argv[2]),
        "wineserverSettle": int(sys.argv[3]),
        "stdoutMarker": int(sys.argv[4]),
        "fileSentinel": int(sys.argv[5]),
    },
    "status": "passed" if all(int(value) == 0 for value in sys.argv[2:]) else "failed",
    "logs": {"directProbe": "logs/powershell-engine/direct-probe.log"},
}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY
  [ "$process_rc" -eq 0 ] && [ "$settle_rc" -eq 0 ] && [ "$stdout_rc" -eq 0 ] && [ "$sentinel_rc" -eq 0 ]
}

if verify_backend; then
  echo "[cage] Reusing verified Windows PowerShell 5.1 backend"
  exit 0
fi

echo "[cage] Installing Windows PowerShell 5.1 backend from WMF 5.1..."
if [ ! -f "$archive" ]; then
  curl -fL --retry 3 --connect-timeout 30 --max-time 1800 -o "$archive.part" "$archive_url"
  mv -f "$archive.part" "$archive"
fi
actual_sha256="$(sha256sum "$archive" | cut -d ' ' -f 1)"
if [ "$actual_sha256" != "$archive_sha256" ]; then
  echo "[cage] ERROR: WMF 5.1 archive checksum mismatch" >&2
  echo "[cage] expected=$archive_sha256 actual=$actual_sha256" >&2
  exit 1
fi

rm -rf "$extract_root" "$payload_root"
mkdir -p "$extract_root/zip" "$extract_root/msu" "$payload_root"
7z x -y "$archive" -o"$extract_root/zip" >"$log_root/wmf-zip-extract.log"
msu="$(find "$extract_root/zip" -iname 'Win7AndW2K8R2-KB3191566-x64.msu' -type f -print -quit)"
test -s "$msu"
7z x -y "$msu" -o"$extract_root/msu" >"$log_root/wmf-msu-extract.log"
cab="$(find "$extract_root/msu" -iname 'Windows6.1-KB3191566-x64.cab' -type f -print -quit)"
test -s "$cab"
test -s "$expand_exe"
cab_win="$(winepath -w "$cab")"
payload_win="$(winepath -w "$payload_root")"

cat > "$work/manifests.txt" <<'EOF'
wow64_microsoft.powershell.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_be98c8f8cfb32e06.manifest
amd64_microsoft.powershell.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_b4441ea69b526c0b.manifest
msil_microsoft.powershell.consolehost_31bf3856ad364e35_7.3.7601.16384_none_8634e813855724c9.manifest
amd64_microsoft.managemen..frastructure.native_31bf3856ad364e35_7.3.7601.16384_none_8ab57567838da803.manifest
x86_microsoft.managemen..frastructure.native_31bf3856ad364e35_7.3.7601.16384_none_d262ac3e9809d109.manifest
amd64_microsoft.powershell.archive_31bf3856ad364e35_7.3.7601.16384_none_f7ab4242f320bef0.manifest
msil_microsoft.powershell.security_31bf3856ad364e35_7.3.7601.16384_none_64c18e3e0eafee92.manifest
amd64_microsoft.packagemanagement.common_31bf3856ad364e35_7.3.7601.16384_none_ee66270965c165ab.manifest
wow64_microsoft.packagemanagement.common_31bf3856ad364e35_7.3.7601.16384_none_f8bad15b9a2227a6.manifest
amd64_microsoft.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_f23f0a687ff51c88.manifest
wow64_microsoft.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_fc93b4bab455de83.manifest
msil_system.management.automation_31bf3856ad364e35_7.3.7601.16384_none_85266a48f56bfafc.manifest
msil_microsoft.powershel..ommands.diagnostics_31bf3856ad364e35_7.3.7601.16384_none_3cbfce2c3881d318.manifest
msil_microsoft.wsman.management_31bf3856ad364e35_7.3.7601.16384_none_60964e40b40fafee.manifest
msil_microsoft.powershell.commands.management_31bf3856ad364e35_7.3.7601.16384_none_c1a0335546714b23.manifest
msil_microsoft.powershell.commands.utility_31bf3856ad364e35_7.3.7601.16384_none_d96091fd5568ce18.manifest
msil_microsoft.management.infrastructure_31bf3856ad364e35_7.3.7601.16384_none_8310156aa31a52f1.manifest
msil_microsoft.wsman.runtime_31bf3856ad364e35_7.3.7601.16384_none_a19b148df40272fb.manifest
msil_microsoft.powershell.graphicalhost_31bf3856ad364e35_7.3.7601.16384_none_c32121af2a1808d4.manifest
amd64_microsoft.powershell.psget_31bf3856ad364e35_7.3.7601.16384_none_c9db05c823f10f09.manifest
wow64_microsoft.powershell.psget_31bf3856ad364e35_7.3.7601.16384_none_d42fb01a5851d104.manifest
msil_policy.1.0.system.management.automation_31bf3856ad364e35_7.3.7601.16384_none_79a60ff187b4c325.manifest
wow64_microsoft.windows.powershell.v3.common_31bf3856ad364e35_7.3.7601.16384_none_8187c53a975bb9ea.manifest
amd64_microsoft.windows.powershell.v3.common_31bf3856ad364e35_7.3.7601.16384_none_77331ae862faf7ef.manifest
wow64_microsoft.packagema..provider.powershell_31bf3856ad364e35_7.3.7601.16384_none_f50f549afdaf3c10.manifest
amd64_microsoft.packagema..provider.powershell_31bf3856ad364e35_7.3.7601.16384_none_eabaaa48c94e7a15.manifest
wow64_microsoft.packagema..ement.coreproviders_31bf3856ad364e35_7.3.7601.16384_none_f05cb06fdbbd6e3c.manifest
amd64_microsoft.packagema..ement.coreproviders_31bf3856ad364e35_7.3.7601.16384_none_e608061da75cac41.manifest
amd64_microsoft.packagema..t.archiverproviders_31bf3856ad364e35_7.3.7601.16384_none_a98e3ebb18648eb6.manifest
wow64_microsoft.packagema..t.archiverproviders_31bf3856ad364e35_7.3.7601.16384_none_b3e2e90d4cc550b1.manifest
amd64_microsoft.packagemanagement.msiprovider_31bf3856ad364e35_7.3.7601.16384_none_ae42a045a84e072e.manifest
wow64_microsoft.packagemanagement.msiprovider_31bf3856ad364e35_7.3.7601.16384_none_b8974a97dcaec929.manifest
amd64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_48be7e79e188387e.manifest
wow64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_531328cc15e8fa79.manifest
EOF

: > "$log_root/wmf-expand.log"
while IFS= read -r manifest; do
  [ -n "$manifest" ] || continue
  timeout --kill-after=10s 180s wine "$expand_exe" "$cab_win" "-f:$manifest" "$payload_win" >>"$log_root/wmf-expand.log" 2>&1
  test -s "$payload_root/$manifest"
done < "$work/manifests.txt"

python3 - "$payload_root" "$work/payload-files.txt" <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
root = Path(sys.argv[1])
output = Path(sys.argv[2])
def local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]
names = []
for manifest in root.glob('*.manifest'):
    tree = ET.parse(manifest)
    for element in tree.iter():
        if local(element.tag) == 'file' and element.attrib.get('name'):
            names.append(element.attrib['name'])
output.write_text('\n'.join(dict.fromkeys(names)) + '\n', encoding='utf-8')
PY

while IFS= read -r filename; do
  [ -n "$filename" ] || continue
  timeout --kill-after=10s 180s wine "$expand_exe" "$cab_win" "-f:$filename" "$payload_win" >>"$log_root/wmf-expand.log" 2>&1
done < "$work/payload-files.txt"

python3 - "$payload_root" "$wine_prefix" <<'PY'
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

payload = Path(sys.argv[1])
prefix = Path(sys.argv[2])
drive_c = prefix / 'drive_c'
system32 = drive_c / 'windows' / 'system32'
syswow64 = drive_c / 'windows' / 'syswow64'
program_files = drive_c / 'Program Files'
program_files_x86 = drive_c / 'Program Files (x86)'
common_files = program_files / 'Common Files'
common_files_x86 = program_files_x86 / 'Common Files'
local64 = system32 / 'WindowsPowerShell' / 'v1.0'
local32 = syswow64 / 'WindowsPowerShell' / 'v1.0'
local64.mkdir(parents=True, exist_ok=True)
local32.mkdir(parents=True, exist_ok=True)

def local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]

def attr(element, name):
    for key, value in element.attrib.items():
        if key.lower() == name.lower():
            return value
    return None

def map_destination(value: str, arch: str) -> Path:
    replacements64 = {
        '$(runtime.system32)': str(system32),
        '$(runtime.programfiles)': str(program_files),
        '$(runtime.wbem)': str(system32 / 'wbem'),
        '$(runtime.commonfiles)': str(common_files),
    }
    replacements32 = {
        '$(runtime.system32)': str(syswow64),
        '$(runtime.programfiles)': str(program_files_x86),
        '$(runtime.wbem)': str(syswow64 / 'wbem'),
        '$(runtime.commonfiles)': str(common_files_x86),
    }
    result = value
    replacements = replacements32 if arch in {'wow64', 'x86'} else replacements64
    for source, destination in replacements.items():
        result = result.replace(source, destination).replace(source.replace('runtime.', 'runtime.').title(), destination)
    result = result.replace('$(runtime.windows)', str(drive_c / 'windows'))
    result = result.replace('$(runtime.Windows)', str(drive_c / 'windows'))
    result = result.replace('$(runtime.inf)', str(drive_c / 'windows' / 'inf'))
    result = result.replace('$(runtime.Inf)', str(drive_c / 'windows' / 'inf'))
    return Path(result.replace('\\', '/'))

def candidates(manifest: Path, filename: str):
    stem = manifest.name[:-len('.manifest')]
    direct = payload / stem / filename
    if direct.exists():
        yield direct
    for path in payload.rglob('*'):
        if path.is_file() and path.name.lower() == filename.lower():
            if path.parent.name.lower() == stem.lower():
                yield path
    for path in payload.rglob('*'):
        if path.is_file() and path.name.lower() == filename.lower():
            yield path

def source_for(manifest: Path, filename: str) -> Path:
    try:
        return next(candidates(manifest, filename))
    except StopIteration as exc:
        raise FileNotFoundError(f'{manifest.name}: missing extracted payload {filename}') from exc

def copy_file(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

for manifest in sorted(payload.glob('*.manifest')):
    tree = ET.parse(manifest)
    identity = next(element for element in tree.iter() if local(element.tag) == 'assemblyIdentity')
    arch = attr(identity, 'processorArchitecture') or 'msil'
    for element in tree.iter():
        if local(element.tag) != 'file':
            continue
        filename = attr(element, 'name')
        if not filename:
            continue
        source = source_for(manifest, filename)
        destination_path = attr(element, 'destinationPath')
        installed = False
        if destination_path:
            destination_dir = map_destination(destination_path, arch)
            copy_file(source, destination_dir / filename)
            installed = True
        for child in element:
            if local(child.tag) != 'link':
                continue
            destination = attr(child, 'destination')
            if destination:
                final_path = map_destination(destination, arch)
                copy_file(source_for(manifest, final_path.name), final_path)
                installed = True
        # CLR probes the executable directory before the GAC. Colocating the
        # selected managed assemblies removes the need for a bootstrap-time CLR
        # metadata reader while preserving CFW's manifest-directed destinations.
        if source.suffix.lower() in {'.dll', '.config', '.ps1', '.psm1', '.psd1', '.cdxml', '.types', '.format'}:
            targets = [local32] if arch in {'wow64', 'x86'} else [local64]
            if arch == 'msil':
                targets = [local64, local32]
            for target in targets:
                copy_file(source, target / filename)
            installed = True
        if not installed:
            target = local32 if arch in {'wow64', 'x86'} else local64
            copy_file(source, target / filename)

for arch, destination in (
    ('amd64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_48be7e79e188387e', local64 / 'ps51.exe'),
    ('wow64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_531328cc15e8fa79', local32 / 'ps51.exe'),
):
    source = payload / arch / 'powershell.exe'
    if not source.exists():
        matches = [path for path in payload.rglob('powershell.exe') if path.parent.name.lower() == arch.lower()]
        if not matches:
            raise FileNotFoundError(f'missing {arch}/powershell.exe')
        source = matches[0]
    copy_file(source, destination)
PY

cat > "$work/powershell51.reg" <<'REG'
REGEDIT4

[HKEY_LOCAL_MACHINE\Software\Microsoft\PowerShell]
[HKEY_LOCAL_MACHINE\Software\Microsoft\PowerShell\1]
"Install"=dword:00000001
[HKEY_LOCAL_MACHINE\Software\Microsoft\PowerShell\1\PowerShellEngine]
"ApplicationBase"="C:\\Windows\\System32\\WindowsPowerShell\\v1.0"
[HKEY_LOCAL_MACHINE\Software\Microsoft\PowerShell\3]
"Install"=dword:00000001
[HKEY_LOCAL_MACHINE\Software\Microsoft\PowerShell\3\PowerShellEngine]
"ApplicationBase"="C:\\Windows\\System32\\WindowsPowerShell\\v1.0"
"ConsoleHostAssemblyName"="Microsoft.PowerShell.ConsoleHost, Version=3.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35, ProcessorArchitecture=msil"
"ConsoleHostModuleName"="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\Microsoft.PowerShell.ConsoleHost.dll"
"PowerShellVersion"="5.1.19041.1"
"PSCompatibleVersion"="1.0, 2.0, 3.0, 4.0, 5.0, 5.1"
"PSPluginWkrModuleName"="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\System.Management.Automation.dll"
"RuntimeVersion"="v4.0.30319"

[HKEY_CURRENT_USER\Environment]
"PWSH_PATH"="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\ps51.exe"
"PSHACKS"="1"
"PS_FROM"=" measure -s "
"PS_TO"=" measure -sum "
REG
reg_win="$(winepath -w "$work/powershell51.reg")"
timeout --kill-after=10s 120s wine regedit /S "$reg_win" >"$log_root/powershell51-registry.log" 2>&1
export PWSH_PATH='C:\windows\system32\WindowsPowerShell\v1.0\ps51.exe'
export PSHACKS=1
export PS_FROM=' measure -s '
export PS_TO=' measure -sum '

verify_backend || {
  echo "[cage] ERROR: Windows PowerShell 5.1 backend verification failed" >&2
  exit 70
}
echo "[cage] Windows PowerShell 5.1 backend verified"
