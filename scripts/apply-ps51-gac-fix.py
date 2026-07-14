from pathlib import Path

p = Path("core/chocolatey/assets/install-powershell51.sh")
s = p.read_text(encoding="utf-8")


def rep(old: str, new: str, label: str) -> None:
    global s
    if old not in s:
        raise SystemExit(f"missing anchor: {label}")
    s = s.replace(old, new, 1)


rep('probe_marker="$probe_root/engine-probe-ok.txt"\n', r'''probe_marker="$probe_root/engine-probe-ok.txt"
policy_key='HKCU\Software\Wine\AppDefaults\ps51.exe\DllOverrides'
policy_log="$log_root/powershell51-wine-policy.log"
failure_trace="$log_root/direct-probe-winedebug.log"
assembly_source="$work/assembly-inventory.cs"
assembly_exe="$work/assembly-inventory.exe"
assembly_map="$work/assembly-inventory.tsv"
assembly_compile_log="$log_root/assembly-inventory-compile.log"
assembly_run_log="$log_root/assembly-inventory-run.log"
gac_log="$log_root/gac-installs.log"
''', 'variables')

rep('mkdir -p "$work" "$extract_root" "$payload_root" "$log_root" "$probe_root" "$(dirname "$metadata")"\n\n', r'''mkdir -p "$work" "$extract_root" "$payload_root" "$log_root" "$probe_root" "$(dirname "$metadata")"

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

''', 'functions')

rep('        "nestedHashes": "logs/powershell-engine/wmf-nested-hashes.log",\n', '''        "nestedHashes": "logs/powershell-engine/wmf-nested-hashes.log",
        "winePolicy": "logs/powershell-engine/powershell51-wine-policy.log",
        "failureTrace": "logs/powershell-engine/direct-probe-winedebug.log",
        "assemblyInventoryCompile": "logs/powershell-engine/assembly-inventory-compile.log",
        "assemblyInventoryRun": "logs/powershell-engine/assembly-inventory-run.log",
        "gacInstalls": "logs/powershell-engine/gac-installs.log",
''', 'metadata logs')

rep(r'''  if [ -s "$probe_marker" ] && grep -Eq '^5\.1([.]|$)' "$probe_marker"; then
    sentinel_rc=0
  else
    sentinel_rc=1
  fi
  set -e

  cat "$normalized_log"
''', r'''  if [ -s "$probe_marker" ] && grep -Eq '^5\.1([.]|$)' "$probe_marker"; then
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
''', 'failure trace')

rep('''if verify_backend; then
  echo "[cage] Reusing verified Windows PowerShell 5.1 backend"
  exit 0
fi
''', '''prepare_ps51_policy
if verify_backend; then
  echo "[cage] Reusing verified Windows PowerShell 5.1 backend"
  exit 0
fi
''', 'initial policy')

rep('''find "$payload_root" -type f -printf '%P\\n' | sort >"$log_root/wmf-payload-inventory.log"

python3 - "$payload_root" "$work/manifests.txt" "$wine_prefix" "$log_root/installed-files.log" "$log_root/skipped-files.log" <<'PY'
''', '''find "$payload_root" -type f -printf '%P\\n' | sort >"$log_root/wmf-payload-inventory.log"
build_assembly_inventory
: > "$gac_log"

python3 - "$payload_root" "$work/manifests.txt" "$wine_prefix" "$log_root/installed-files.log" "$log_root/skipped-files.log" "$assembly_map" "$gac_log" <<'PY'
''', 'python invocation')

rep('''skipped_log = Path(sys.argv[5])
drive_c = prefix / "drive_c"
''', '''skipped_log = Path(sys.argv[5])
assembly_map_path = Path(sys.argv[6])
gac_log = Path(sys.argv[7])
drive_c = prefix / "drive_c"
''', 'python args')

rep('''local64.mkdir(parents=True, exist_ok=True)
local32.mkdir(parents=True, exist_ok=True)

required_components = {
''', '''local64.mkdir(parents=True, exist_ok=True)
local32.mkdir(parents=True, exist_ok=True)

assembly_info = {}
for line in assembly_map_path.read_text(encoding="utf-8-sig").splitlines():
    parts = line.split("\\t")
    if len(parts) != 4:
        continue
    relative, name, version, token = parts
    assembly_info[relative.replace("\\\\", "/").lower()] = (name, version, token)

gac_installs = []

required_components = {
''', 'assembly map')

rep('''def copy_file(source: Path, destination: Path, installed: list[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    installed.append(str(destination.relative_to(prefix)))

selected_names =''', '''def copy_file(source: Path, destination: Path, installed: list[str]) -> None:
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

selected_names =''', 'gac functions')

rep('''        destination_path = attr(element, "destinationPath")
        if destination_path:
            copy_file(source, map_destination(destination_path, arch) / filename, installed)
        for child in element:
''', '''        destination_path = attr(element, "destinationPath")
        if destination_path:
            copy_file(source, map_destination(destination_path, arch) / filename, installed)
        elif arch.lower() in {"msil", "amd64", "x86"} and source.suffix.lower() in {".dll", ".config"}:
            install_gac(source, arch, installed)
        for child in element:
''', 'gac install loop')

rep('''inventory.write_text("\\n".join(sorted(set(installed))) + "\\n", encoding="utf-8")
skipped_log.write_text("\\n".join(skipped) + ("\\n" if skipped else ""), encoding="utf-8")
PY
''', '''inventory.write_text("\\n".join(sorted(set(installed))) + "\\n", encoding="utf-8")
skipped_log.write_text("\\n".join(skipped) + ("\\n" if skipped else ""), encoding="utf-8")
gac_log.write_text("\\n".join(sorted(set(gac_installs))) + ("\\n" if gac_installs else ""), encoding="utf-8")
if not gac_installs:
    raise RuntimeError("no managed PowerShell assemblies were installed into the .NET GAC")
PY
''', 'gac final')

rep('timeout --kill-after=10s 120s wine regedit /S "$reg_win" >"$log_root/powershell51-registry.log" 2>&1\n', 'timeout --kill-after=10s 120s wine regedit /S "$reg_win" >"$log_root/powershell51-registry.log" 2>&1\nprepare_ps51_policy\n', 'final policy')

p.write_text(s, encoding="utf-8")
print(f"patched {p}: {len(s.splitlines())} lines")
