from pathlib import Path

path = Path("core/chocolatey/assets/install-powershell51.sh")
text = path.read_text(encoding="utf-8")

old = '''build_assembly_inventory() {
  csc_exe=""
  for candidate in \\
    "$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe" \\
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
  timeout --kill-after=10s 180s wine "$csc_exe" /nologo /target:exe "/out:$exe_win" "$source_win" \\
    >"$assembly_compile_log" 2>&1
  test -s "$assembly_exe"
  timeout --kill-after=10s 240s wine "$assembly_exe" "$payload_win_for_inventory" "$map_win" \\
    >"$assembly_run_log" 2>&1
  test -s "$assembly_map"
}
'''

new = '''build_assembly_inventory() {
  csc_exe=""
  framework_dir=""
  for candidate in \\
    "$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe" \\
    "$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/csc.exe"; do
    if [ -s "$candidate" ]; then
      csc_exe="$candidate"
      framework_dir="$(dirname "$candidate")"
      break
    fi
  done
  if [ -z "$csc_exe" ]; then
    echo "[cage] ERROR: .NET Framework C# compiler is unavailable" >&2
    exit 69
  fi
  mscorlib="$framework_dir/mscorlib.dll"
  if [ ! -s "$mscorlib" ]; then
    echo "[cage] ERROR: matching .NET Framework mscorlib.dll is unavailable" >&2
    exit 69
  fi
  write_assembly_inventory_helper
  source_win="$(winepath -w "$assembly_source")"
  exe_win="$(winepath -w "$assembly_exe")"
  mscorlib_win="$(winepath -w "$mscorlib")"
  payload_win_for_inventory="$(winepath -w "$payload_root")"
  map_win="$(winepath -w "$assembly_map")"
  rm -f "$assembly_exe" "$assembly_map"
  timeout --kill-after=10s 180s wine "$csc_exe" \\
    /nologo /noconfig /nostdlib+ /target:exe "/reference:$mscorlib_win" \\
    "/out:$exe_win" "$source_win" >"$assembly_compile_log" 2>&1
  test -s "$assembly_exe"
  timeout --kill-after=10s 240s wine "$assembly_exe" "$payload_win_for_inventory" "$map_win" \\
    >"$assembly_run_log" 2>&1
  test -s "$assembly_map"
}
'''

if old not in text:
    raise SystemExit("current PS5.1 assembly inventory block did not match")

path.write_text(text.replace(old, new, 1), encoding="utf-8")
print(f"patched {path}")
