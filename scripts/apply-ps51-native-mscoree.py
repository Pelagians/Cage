from pathlib import Path

path = Path("core/chocolatey/assets/install-powershell51.sh")
text = path.read_text(encoding="utf-8")
old = r'''prepare_ps51_policy() {
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
'''
new = r'''prepare_ps51_policy() {
  : > "$policy_log"
  shell32_policy=builtin
  wine_version_file="$wine_prefix/drive_c/windows/system32/wine_version.txt"
  native_mscoree64="$wine_prefix/drive_c/windows/system32/mscoree.dll"
  native_clr64="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"
  if [ -f "$wine_version_file" ] && grep -qi '(Staging)' "$wine_version_file"; then
    shell32_policy=native
  fi
  {
    echo "[cage] ps51.exe shell32 policy=$shell32_policy"
    echo "[cage] ps51.exe mscoree policy=native"
    echo "[cage] native mscoree64 bytes=$(wc -c < \"$native_mscoree64\" 2>/dev/null || echo 0)"
    echo "[cage] native clr64 bytes=$(wc -c < \"$native_clr64\" 2>/dev/null || echo 0)"
  } | tee -a "$policy_log"
  if [ ! -s "$native_mscoree64" ] || [ ! -s "$native_clr64" ]; then
    echo "[cage] ERROR: native .NET 4 loader closure is incomplete" >&2
    exit 69
  fi
  timeout --kill-after=10s 120s wine reg add "$policy_key" /v shell32 /d "$shell32_policy" /f \
    >>"$policy_log" 2>&1
  timeout --kill-after=10s 120s wine reg add "$policy_key" /v mscoree /d native /f \
    >>"$policy_log" 2>&1
  timeout --kill-after=10s 90s wineserver -w >>"$policy_log" 2>&1
}
'''
if old not in text:
    raise SystemExit("PS5.1 policy function did not match")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print(f"patched {path}")
