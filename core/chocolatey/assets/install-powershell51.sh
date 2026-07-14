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
expand_exe="$wine_prefix/drive_c/windows/system32/expnd/expand.exe"
dpx_dll="$wine_prefix/drive_c/windows/system32/dpx.dll"
probe_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
probe_script="$probe_root/engine-probe.ps1"
probe_marker="$probe_root/engine-probe-ok.txt"
policy_key='HKCU\Software\Wine\AppDefaults\ps51.exe\DllOverrides'
policy_log="$log_root/powershell51-wine-policy.log"
failure_trace="$log_root/direct-probe-winedebug.log"
assembly_source="$work/assembly-inventory.cs"
assembly_exe="$work/assembly-inventory.exe"
assembly_map="$work/assembly-inventory.tsv"
assembly_compile_log="$log_root/assembly-inventory-compile.log"
assembly_run_log="$log_root/assembly-inventory-run.log"
gac_log="$log_root/gac-installs.log"

mkdir -p "$work" "$extract_root" "$payload_root" "$log_root" "$probe_root" "$(dirname "$metadata")"

prepare_ps51_policy() {
  : > "$policy_log"
  shell32_policy=builtin
  wine_version_file="$wine_prefix/drive_c/windows/system32/wine_version.txt"
  if [ -f "$wine_version_file" ] && grep -qi '(Staging)' "$wine_version_file"; then
    shell32_policy=native
  fi
  echo "[cage] ps51.exe shell32 policy=$shell32_policy" | tee -a "$policy_log"
  timeout --kill-after=10s 120s wine reg add "$policy_key" /v shell32 /d "$shell32_policy" /f \
    >>"$policy_log" 2>&1
  timeout --kill-after=10s 90s wineserver -w >>"$policy_log" 2>&1
}

write_assembly_inventory_helper() {
  cat > "$assembly_source.part" <<'CS'
using System;
using System.IO;
using System.Reflection;
using System.Text;

internal static class CageAssemblyInventory
{
    private static string Hex(byte[] bytes)
    {
        if (bytes == null || bytes.Length == 0) return string.Empty;
        StringBuilder builder = new StringBuilder(bytes.Length * 2);
        foreach (byte value in bytes) builder.Append(value.ToString("x2"));
        return builder.ToString();
    }

    public static int Main(string[] args)
    {
        if (args.Length != 2) return 64;
        string root = Path.GetFullPath(args[0]);
        using (StreamWriter writer = new StreamWriter(args[1], false, new UTF8Encoding(false)))
        {
            foreach (string file in Directory.GetFiles(root, "*.dll", SearchOption.AllDirectories))
            {
                try
                {
                    AssemblyName assembly = AssemblyName.GetAssemblyName(file);
                    string relative = file.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar).Replace('\\', '/');
                    writer.Write(relative);
                    writer.Write('\t');
                    writer.Write(assembly.Name);
                    writer.Write('\t');
                    writer.Write(assembly.Version == null ? string.Empty : assembly.Version.ToString());
                    writer.Write('\t');
                    writer.WriteLine(Hex(assembly.GetPublicKeyToken()));
                }
                catch (BadImageFormatException) { }
                catch (FileLoadException) { }
            }
        }
        return 0;
    }
}
CS
  mv -f "$assembly_source.part" "$assembly_source"
}

build_assembly_inventory() {
  csc_exe=""
  for candidate in \
    "$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe" \
    "$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/csc.exe"; do
    if [ -s "$candidate" ]; then csc_exe="$candidate"; break; fi
  done
  if [ -z "$csc_exe" ]; then
    echo "[cage] ERROR: .NET Framework C# compiler is unavailable" >&2
    exit 69
  fi
  write_assembly_inventory_helper
  source_win="$(winepath -w "$assembly_source")"
  exe_win="$(winepath -w "$assembly_exe")"
  payload_win_for_inventory="$(winepath -w "$payload_root")"
  map_win="$(winepath -w "$assembly_map")"
  rm -f "$assembly_exe" "$assembly_map"
  timeout --kill-after=10s 180s wine "$csc_exe" /nologo /target:exe "/out:$exe_win" "$source_win" \
    >"$assembly_compile_log" 2>&1
  test -s "$assembly_exe"
  timeout --kill-after=10s 240s wine "$assembly_exe" "$payload_win_for_inventory" "$map_win" \
    >"$assembly_run_log" 2>&1
  test -s "$assembly_map"
}

write_engine_metadata() {
  process_rc="$1"
  settle_rc="$2"
  stdout_rc="$3"
  sentinel_rc="$4"
  python3 - "$metadata" "$process_rc" "$settle_rc" "$stdout_rc" "$sentinel_rc" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
return_codes = {
    "process": int(sys.argv[2]),
    "wineserverSettle": int(sys.argv[3]),
    "stdoutMarker": int(sys.argv[4]),
    "fileSentinel": int(sys.argv[5]),
}
record = {
    "schemaVersion": "cage.powershell-engine/v1",
    "provider": "windows-powershell-5.1-cfw",
    "source": "Win7AndW2K8R2-KB3191566-x64",
    "returnCodes": return_codes,
    "status": "passed" if all(value == 0 for value in return_codes.values()) else "failed",
    "logs": {
        "directProbe": "logs/powershell-engine/direct-probe.log",
        "payloadExtraction": "logs/powershell-engine/wmf-dpx-extract.log",
        "payloadInventory": "logs/powershell-engine/wmf-payload-inventory.log",
        "installationInventory": "logs/powershell-engine/installed-files.log",
        "skippedPayloads": "logs/powershell-engine/skipped-files.log",
        "nestedHashes": "logs/powershell-engine/wmf-nested-hashes.log",
        "winePolicy": "logs/powershell-engine/powershell51-wine-policy.log",
        "failureTrace": "logs/powershell-engine/direct-probe-winedebug.log",
        "assemblyInventoryCompile": "logs/powershell-engine/assembly-inventory-compile.log",
        "assemblyInventoryRun": "logs/powershell-engine/assembly-inventory-run.log",
        "gacInstalls": "logs/powershell-engine/gac-installs.log",
    },
}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY
}

verify_backend() {
  [ -s "$backend64" ] || return 1
  [ -s "$backend32" ] || return 1

  cat > "$probe_script.part" <<'PS1'
param([Parameter(Mandatory = $true)][string]$MarkerPath)
$ErrorActionPreference = 'Stop'
$version = $PSVersionTable.PSVersion.ToString()
[System.IO.File]::WriteAllText($MarkerPath, $version)
[Console]::Out.WriteLine('[cage] engine-version=' + $version)
PS1
  mv -f "$probe_script.part" "$probe_script"
  rm -f "$probe_marker"

  probe_script_win="$(winepath -w "$probe_script")"
  probe_marker_win="$(winepath -w "$probe_marker")"
  backend_log="$log_root/direct-probe.log"
  normalized_log="$log_root/direct-probe.normalized.log"

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
  if [ "$process_rc" -ne 0 ] || [ "$stdout_rc" -ne 0 ] || [ "$sentinel_rc" -ne 0 ]; then
    WINEDEBUG=+process,+loaddll,+seh,+mscoree timeout --kill-after=10s 90s \
      wine "$backend64" -NoLogo -NoProfile -NonInteractive -Command \
      '[Console]::Out.WriteLine("[cage] ps51-trace-alive")' >"$failure_trace" 2>&1
    trace_rc="$?"
    printf '\n[cage] failure-trace-rc=%s\n' "$trace_rc" >>"$failure_trace"
  else
    : > "$failure_trace"
  fi
  set -e

  cat "$normalized_log"
  write_engine_metadata "$process_rc" "$settle_rc" "$stdout_rc" "$sentinel_rc"
  [ "$process_rc" -eq 0 ] && [ "$settle_rc" -eq 0 ] && [ "$stdout_rc" -eq 0 ] && [ "$sentinel_rc" -eq 0 ]
}

prepare_ps51_policy
if verify_backend; then
  echo "[cage] Reusing verified Windows PowerShell 5.1 backend"
  exit 0
fi

if [ ! -s "$expand_exe" ] || [ ! -s "$dpx_dll" ]; then
  echo "[cage] ERROR: CFW DPX extraction helper is not installed" >&2
  echo "[cage] expected expand=$expand_exe dpx=$dpx_dll" >&2
  exit 68
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
{
  echo "archive $(sha256sum "$archive" | cut -d ' ' -f 1)"
  echo "msu $(sha256sum "$msu" | cut -d ' ' -f 1)"
  echo "cab $(sha256sum "$cab" | cut -d ' ' -f 1)"
} >"$log_root/wmf-nested-hashes.log"

# Ordinary 7z extraction exposes the XML manifests but not the DPX-compressed
# component payloads. Select only the PowerShell/PackageManagement manifests;
# the CFW native expander below materializes their files by component.
7z x -y "$cab" -o"$payload_root" '*.manifest' >"$log_root/wmf-manifest-extract.log"
python3 - "$payload_root" "$work/manifests.txt" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
output = Path(sys.argv[2])
tokens = (
    "microsoft.powershell.",
    "system.management.automation_",
    "microsoft.windows.powershell.v3.common_",
    "microsoft-windows-powershell-exe_",
    "microsoft.packagemanagement",
    "microsoft.management.infrastructure_",
    "microsoft.wsman.",
)
selected = []
for path in sorted(root.glob("*.manifest")):
    name = path.name.lower()
    if "_7.3.7601.16384_" not in name or "languagepack" in name:
        continue
    if any(token in name for token in tokens):
        selected.append(path.name)
if not selected:
    raise SystemExit("no WMF 5.1 PowerShell manifests selected")
output.write_text("\n".join(selected) + "\n", encoding="utf-8")
PY

cab_win="$(winepath -w "$cab")"
payload_win="$(winepath -w "$payload_root")"
: > "$log_root/wmf-dpx-extract.log"
while IFS= read -r manifest; do
  [ -n "$manifest" ] || continue
  timeout --kill-after=10s 180s wine "$expand_exe" "$cab_win" "-f:$manifest" "$payload_win" \
    >>"$log_root/wmf-dpx-extract.log" 2>&1
  test -s "$payload_root/$manifest"
done < "$work/manifests.txt"

python3 - "$payload_root" "$work/manifests.txt" "$work/payload-plan.txt" <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(sys.argv[1])
manifest_list = Path(sys.argv[2])
output = Path(sys.argv[3])

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def attr(element, name: str):
    for key, value in element.attrib.items():
        if key.lower() == name.lower():
            return value
    return None

names = []
for manifest_name in manifest_list.read_text(encoding="utf-8").splitlines():
    if not manifest_name:
        continue
    tree = ET.parse(root / manifest_name)
    for element in tree.iter():
        if local(element.tag) != "file":
            continue
        for candidate in (attr(element, "name"), attr(element, "sourceName")):
            if candidate and candidate.lower() not in {value.lower() for value in names}:
                names.append(candidate)
output.write_text("\n".join(names) + "\n", encoding="utf-8")
PY

while IFS= read -r filename; do
  [ -n "$filename" ] || continue
  set +e
  timeout --kill-after=10s 180s wine "$expand_exe" "$cab_win" "-f:$filename" "$payload_win" \
    >>"$log_root/wmf-dpx-extract.log" 2>&1
  extract_rc="$?"
  set -e
  if [ "$extract_rc" -ne 0 ]; then
    printf 'extract rc=%s file=%s\n' "$extract_rc" "$filename" >>"$log_root/wmf-dpx-extract.log"
  fi
done < "$work/payload-plan.txt"
find "$payload_root" -type f -printf '%P\n' | sort >"$log_root/wmf-payload-inventory.log"
build_assembly_inventory
: > "$gac_log"

python3 - "$payload_root" "$work/manifests.txt" "$wine_prefix" "$log_root/installed-files.log" "$log_root/skipped-files.log" "$assembly_map" "$gac_log" <<'PY'
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

payload = Path(sys.argv[1])
manifest_list = Path(sys.argv[2])
prefix = Path(sys.argv[3])
inventory = Path(sys.argv[4])
skipped_log = Path(sys.argv[5])
assembly_map_path = Path(sys.argv[6])
gac_log = Path(sys.argv[7])
drive_c = prefix / "drive_c"
system32 = drive_c / "windows" / "system32"
syswow64 = drive_c / "windows" / "syswow64"
program_files = drive_c / "Program Files"
program_files_x86 = drive_c / "Program Files (x86)"
common_files = program_files / "Common Files"
common_files_x86 = program_files_x86 / "Common Files"
local64 = system32 / "WindowsPowerShell" / "v1.0"
local32 = syswow64 / "WindowsPowerShell" / "v1.0"
local64.mkdir(parents=True, exist_ok=True)
local32.mkdir(parents=True, exist_ok=True)

assembly_info = {}
for line in assembly_map_path.read_text(encoding="utf-8-sig").splitlines():
    parts = line.split("\t")
    if len(parts) != 4:
        continue
    relative, name, version, token = parts
    assembly_info[relative.replace("\\", "/").lower()] = (name, version, token)

gac_installs = []

required_components = {
    "msil_system.management.automation_31bf3856ad364e35_7.3.7601.16384_none_85266a48f56bfafc",
    "msil_microsoft.powershell.consolehost_31bf3856ad364e35_7.3.7601.16384_none_8634e813855724c9",
    "msil_microsoft.powershell.security_31bf3856ad364e35_7.3.7601.16384_none_64c18e3e0eafee92",
    "msil_microsoft.powershell.commands.management_31bf3856ad364e35_7.3.7601.16384_none_c1a0335546714b23",
    "msil_microsoft.powershell.commands.utility_31bf3856ad364e35_7.3.7601.16384_none_d96091fd5568ce18",
    "amd64_microsoft.windows.powershell.v3.common_31bf3856ad364e35_7.3.7601.16384_none_77331ae862faf7ef",
    "wow64_microsoft.windows.powershell.v3.common_31bf3856ad364e35_7.3.7601.16384_none_8187c53a975bb9ea",
    "amd64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_48be7e79e188387e",
    "wow64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_531328cc15e8fa79",
}

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def attr(element, name: str):
    for key, value in element.attrib.items():
        if key.lower() == name.lower():
            return value
    return None

def replace_token(value: str, token: str, replacement: Path) -> str:
    return re.sub(re.escape(token), str(replacement), value, flags=re.IGNORECASE)

def map_destination(value: str, arch: str) -> Path:
    is_32 = arch.lower() in {"wow64", "x86"}
    result = value
    replacements = {
        "$(runtime.system32)": syswow64 if is_32 else system32,
        "$(runtime.programfiles)": program_files_x86 if is_32 else program_files,
        "$(runtime.wbem)": (syswow64 if is_32 else system32) / "wbem",
        "$(runtime.commonfiles)": common_files_x86 if is_32 else common_files,
        "$(runtime.windows)": drive_c / "windows",
        "$(runtime.inf)": drive_c / "windows" / "inf",
    }
    for token, replacement in replacements.items():
        result = replace_token(result, token, replacement)
    if "$(" in result:
        raise ValueError(f"unresolved manifest destination token: {value}")
    return Path(result.replace("\\", "/"))

def find_case_insensitive(root: Path, relative: str) -> Path | None:
    current = root
    for part in Path(relative.replace("\\", "/")).parts:
        if not current.is_dir():
            return None
        match = next((entry for entry in current.iterdir() if entry.name.lower() == part.lower()), None)
        if match is None:
            return None
        current = match
    return current

def source_for(manifest: Path, destination_name: str, source_name: str | None) -> Path | None:
    component = manifest.name[:-len(".manifest")]
    names = []
    for candidate in (destination_name, source_name):
        if candidate and candidate.lower() not in {name.lower() for name in names}:
            names.append(candidate)
    for name in names:
        direct = find_case_insensitive(payload, f"{component}/{name}")
        if direct and direct.is_file():
            return direct
    for name in names:
        matches = [
            path for path in payload.rglob("*")
            if path.is_file() and path.name.lower() == name.lower()
            and path.parent.name.lower() == component.lower()
        ]
        if matches:
            return matches[0]
    for name in names:
        matches = [path for path in payload.rglob("*") if path.is_file() and path.name.lower() == name.lower()]
        if len(matches) == 1:
            return matches[0]
    return None

def copy_file(source: Path, destination: Path, installed: list[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    installed.append(str(destination.relative_to(prefix)))

def assembly_metadata(source: Path):
    metadata_source = source
    if source.suffix.lower() == ".config":
        metadata_source = source.with_suffix(".dll")
    try:
        relative = metadata_source.relative_to(payload).as_posix().lower()
    except ValueError:
        return None
    return assembly_info.get(relative)

def install_gac(source: Path, arch: str, installed: list[str]) -> None:
    info = assembly_metadata(source)
    if info is None:
        return
    assembly_name, version, token = info
    if not assembly_name or not version or not token:
        return
    arch_lower = arch.lower()
    if arch_lower == "msil":
        gac_kind = "GAC_MSIL"
    elif arch_lower == "amd64":
        gac_kind = "GAC_64"
    elif arch_lower == "x86":
        gac_kind = "GAC_32"
    else:
        return
    destination = drive_c / "windows" / "Microsoft.NET" / "assembly" / gac_kind / assembly_name / ("v4.0_" + version + "__" + token) / source.name
    copy_file(source, destination, installed)
    gac_installs.append(str(destination.relative_to(prefix)))

selected_names = [line.strip() for line in manifest_list.read_text(encoding="utf-8").splitlines() if line.strip()]
selected_manifests = [payload / name for name in selected_names]
missing_manifests = [str(path) for path in selected_manifests if not path.is_file()]
if missing_manifests:
    raise FileNotFoundError("missing selected WMF manifests: " + ", ".join(missing_manifests))

installed = []
skipped = []
for manifest in selected_manifests:
    component = manifest.name[:-len(".manifest")]
    required = component.lower() in required_components
    tree = ET.parse(manifest)
    identity = next(element for element in tree.iter() if local(element.tag) == "assemblyIdentity")
    arch = attr(identity, "processorArchitecture") or "msil"
    target_dirs = [local32] if arch.lower() in {"wow64", "x86"} else [local64]
    if arch.lower() == "msil":
        target_dirs = [local64, local32]

    for element in tree.iter():
        if local(element.tag) != "file":
            continue
        filename = attr(element, "name")
        source_name = attr(element, "sourceName")
        if not filename:
            continue
        source = source_for(manifest, filename, source_name)
        if source is None:
            message = f"{manifest.name}: missing payload name={filename} sourceName={source_name or '-'}"
            if required:
                raise FileNotFoundError(message)
            skipped.append(message)
            continue

        destination_path = attr(element, "destinationPath")
        if destination_path:
            copy_file(source, map_destination(destination_path, arch) / filename, installed)
        elif arch.lower() in {"msil", "amd64", "x86"} and source.suffix.lower() in {".dll", ".config"}:
            install_gac(source, arch, installed)
        for child in element:
            if local(child.tag) != "link":
                continue
            destination = attr(child, "destination")
            if destination:
                copy_file(source, map_destination(destination, arch), installed)
        for target_dir in target_dirs:
            copy_file(source, target_dir / filename, installed)

for component, destination in (
    ("amd64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_48be7e79e188387e", local64 / "ps51.exe"),
    ("wow64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_531328cc15e8fa79", local32 / "ps51.exe"),
):
    source = find_case_insensitive(payload, f"{component}/powershell.exe")
    if source is None or not source.is_file():
        raise FileNotFoundError(f"missing required {component}/powershell.exe")
    copy_file(source, destination, installed)

required_outputs = [
    local64 / "ps51.exe",
    local32 / "ps51.exe",
    local64 / "System.Management.Automation.dll",
    local64 / "Microsoft.PowerShell.ConsoleHost.dll",
    local64 / "Microsoft.PowerShell.Commands.Management.dll",
    local64 / "Microsoft.PowerShell.Commands.Utility.dll",
]
missing_outputs = [str(path) for path in required_outputs if not path.is_file()]
if missing_outputs:
    raise FileNotFoundError("missing required PS5.1 outputs: " + ", ".join(missing_outputs))

inventory.write_text("\n".join(sorted(set(installed))) + "\n", encoding="utf-8")
skipped_log.write_text("\n".join(skipped) + ("\n" if skipped else ""), encoding="utf-8")
gac_log.write_text("\n".join(sorted(set(gac_installs))) + ("\n" if gac_installs else ""), encoding="utf-8")
if not gac_installs:
    raise RuntimeError("no managed PowerShell assemblies were installed into the .NET GAC")
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
prepare_ps51_policy
export PWSH_PATH='C:\windows\system32\WindowsPowerShell\v1.0\ps51.exe'
export PSHACKS=1
export PS_FROM=' measure -s '
export PS_TO=' measure -sum '

verify_backend || {
  echo "[cage] ERROR: Windows PowerShell 5.1 backend verification failed" >&2
  exit 70
}
echo "[cage] Windows PowerShell 5.1 backend verified"
