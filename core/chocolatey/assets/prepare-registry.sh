set -eu
unset WINEDLLOVERRIDES
echo "[cage] Preparing Wine registry for Chocolatey..."
pwsh_win='C:\Program Files\PowerShell\7\pwsh.exe'
timeout "${CAGE_WINECFG_TIMEOUT:-120s}" winecfg /v win10
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Software\Wine\DllOverrides' /v mscoree /t REG_SZ /d native /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\Software\Microsoft\.NETFramework' /v OnlyUseLatestCLR /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Microsoft\.NETFramework\Policy\v2.0' /v 50727 /t REG_SZ /d 50727-50727 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.0' /v Install /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.0' /v SP /t REG_DWORD /d 2 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.0\Setup' /v InstallSuccess /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.5' /v Install /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.5' /v SP /t REG_DWORD /d 1 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Software\Microsoft\Avalon.Graphics' /v DisableHWAcceleration /t REG_DWORD /d 0 /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Classes\CLSID\{0A29FF9E-7F9C-4437-8B11-F424491E3931}\InprocServer32' /ve /t REG_SZ /d 'C:\Windows\System32\mscoree.dll' /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKLM\SOFTWARE\Classes\CLSID\{0A29FF9E-7F9C-4437-8B11-F424491E3931}\InprocServer32' /v ThreadingModel /t REG_SZ /d Both /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Environment' /v PS7 /t REG_SZ /d "$pwsh_win" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Software\Wine\AppDefaults\pwsh.exe\DllOverrides' /v amsi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Software\Wine\AppDefaults\pwsh.exe\DllOverrides' /v dwmapi /d "" /f
timeout "${CAGE_WINE_REG_TIMEOUT:-120s}" wine reg add 'HKCU\Software\Wine\AppDefaults\pwsh.exe\DllOverrides' /v rpcrt4 /d native,builtin /f
echo "[cage] Wine registry prepared for Chocolatey"
