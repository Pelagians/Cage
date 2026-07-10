set -eu
unset WINEDLLOVERRIDES
echo "[cage] Install PowerShell {{POWERSHELL_VERSION}} MSI for Chocolatey"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
pwsh_cache="$module_cache/powershell-msi/{{POWERSHELL_VERSION}}"
pwsh_msi="$pwsh_cache/{{POWERSHELL_MSI_NAME}}"
pwsh_msi_url="{{POWERSHELL_MSI_URL}}"
pwsh_msi_sha256="{{POWERSHELL_MSI_SHA256}}"
pwsh_exe="$wine_prefix/drive_c/Program Files/PowerShell/7/pwsh.exe"
pwsh_product_key='HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{POWERSHELL_MSI_PRODUCT_CODE}}}'
mkdir -p "$pwsh_cache"
echo "[cage] Resolving PowerShell {{POWERSHELL_VERSION}} MSI from verified cache..."
cage_fetch_verified "$pwsh_msi_url" "$pwsh_msi_sha256" "$pwsh_msi" "{{BOOTSTRAP_PROFILE_ID}}"
actual_pwsh_msi_sha="$(sha256sum "$pwsh_msi" | cut -d ' ' -f 1)"
if [ "$actual_pwsh_msi_sha" != "$pwsh_msi_sha256" ]; then
  echo "[cage] ERROR: PowerShell MSI checksum mismatch"
  echo "[cage]   expected: $pwsh_msi_sha256"
  echo "[cage]   actual:   $actual_pwsh_msi_sha"
  exit 1
fi
pwsh_msi_win="$(winepath -w "$pwsh_msi")"
pwsh_msiexec_log="$pwsh_cache/powershell-msiexec.log"
pwsh_msiexec_log_win="$(winepath -w "$pwsh_msiexec_log")"
rm -f "$pwsh_msiexec_log"
echo "[cage] Installing PowerShell {{POWERSHELL_VERSION}} through dedicated MSI step..."
echo "[cage] PowerShell MSI: $pwsh_msi_win"
set +e
timeout "${CAGE_POWERSHELL_MSI_TIMEOUT:-1200s}" wine msiexec /i "$pwsh_msi_win" ADD_EXPLORER_CONTEXT_MENU_OPENPOWERSHELL=0 ENABLE_PSREMOTING=0 REGISTER_MANIFEST=1 USE_MU=0 ENABLE_MU=0 /QN /NORESTART /L*v "$pwsh_msiexec_log_win"
pwsh_msi_rc="$?"
set -e
if [ -f "$pwsh_msiexec_log" ]; then
  echo "[cage] PowerShell MSI failure markers:"
  grep -nEi 'Return value 3|MainEngineThread|Error [0-9]+|Fatal error' "$pwsh_msiexec_log" | head -80 | sed 's/^/[powershell-msi-marker] /' || true
  echo "[cage] PowerShell MSI log tail:"
  tail -120 "$pwsh_msiexec_log" | sed 's/^/[powershell-msi] /'
fi
if [ "$pwsh_msi_rc" -ne 0 ]; then
  echo "[cage] PowerShell MSI Wine exit code: $pwsh_msi_rc"
fi
if [ ! -f "$pwsh_exe" ]; then
  echo "[cage] ERROR: PowerShell MSI did not install pwsh.exe: $pwsh_exe"
  exit 68
fi
test -f "$pwsh_exe"
chmod +x "$pwsh_exe"
set +e
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg query "$pwsh_product_key" >/dev/null 2>&1
pwsh_product_rc="$?"
set -e
if [ "$pwsh_product_rc" -ne 0 ]; then
  echo "[cage] WARNING: PowerShell MSI product registry key not found: $pwsh_product_key"
else
  echo "[cage] PowerShell MSI product registry key present"
fi
echo "[cage] PowerShell MSI installed: $pwsh_exe"
