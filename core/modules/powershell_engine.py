"""Deterministic PowerShell engine providers for Cage modules."""
from __future__ import annotations

import base64

from core.chocolatey import (
    asset_sha256,
    get_bootstrap_profile,
    load_asset,
    load_asset_bytes,
    render_asset,
)

from ..build_step import BuildStep

POWERSHELL_VERSION = "7.4.11"
POWERSHELL_ZIP_NAME = f"PowerShell-{POWERSHELL_VERSION}-win-x64.zip"
POWERSHELL_ZIP_URL = (
    "https://github.com/PowerShell/PowerShell/releases/download/"
    f"v{POWERSHELL_VERSION}/{POWERSHELL_ZIP_NAME}"
)
POWERSHELL_ZIP_SHA256 = "558c4115cc6b96cc6a67d74bee40012cf8d38767537f8d2857dc3fa30a63cc63"
WINDOWS_POWERSHELL_PROVIDER = "windows-powershell-5.1-cfw"
CFW_DPX_PROVIDER = "cfw-dpx-helper-aik-winpe"
CFW_MSCOREE_PROVIDER = "cfw-native-mscoree-kb958488"

# Exact component contract used by CFW's working func_ps51 implementation.
# Microsoft shortens several servicing component names with "..", so token
# matching silently omitted required native MI and PackageManagement providers.
_CFW_PS51_MANIFESTS = (
    "wow64_microsoft.powershell.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_be98c8f8cfb32e06.manifest",
    "amd64_microsoft.powershell.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_b4441ea69b526c0b.manifest",
    "msil_microsoft.powershell.consolehost_31bf3856ad364e35_7.3.7601.16384_none_8634e813855724c9.manifest",
    "amd64_microsoft.managemen..frastructure.native_31bf3856ad364e35_7.3.7601.16384_none_8ab57567838da803.manifest",
    "x86_microsoft.managemen..frastructure.native_31bf3856ad364e35_7.3.7601.16384_none_d262ac3e9809d109.manifest",
    "amd64_microsoft.powershell.archive_31bf3856ad364e35_7.3.7601.16384_none_f7ab4242f320bef0.manifest",
    "msil_microsoft.powershell.security_31bf3856ad364e35_7.3.7601.16384_none_64c18e3e0eafee92.manifest",
    "amd64_microsoft.packagemanagement.common_31bf3856ad364e35_7.3.7601.16384_none_ee66270965c165ab.manifest",
    "wow64_microsoft.packagemanagement.common_31bf3856ad364e35_7.3.7601.16384_none_f8bad15b9a2227a6.manifest",
    "amd64_microsoft.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_f23f0a687ff51c88.manifest",
    "wow64_microsoft.packagemanagement_31bf3856ad364e35_7.3.7601.16384_none_fc93b4bab455de83.manifest",
    "msil_system.management.automation_31bf3856ad364e35_7.3.7601.16384_none_85266a48f56bfafc.manifest",
    "msil_microsoft.powershel..ommands.diagnostics_31bf3856ad364e35_7.3.7601.16384_none_3cbfce2c3881d318.manifest",
    "msil_microsoft.wsman.management_31bf3856ad364e35_7.3.7601.16384_none_60964e40b40fafee.manifest",
    "msil_microsoft.powershell.commands.management_31bf3856ad364e35_7.3.7601.16384_none_c1a0335546714b23.manifest",
    "msil_microsoft.powershell.commands.utility_31bf3856ad364e35_7.3.7601.16384_none_d96091fd5568ce18.manifest",
    "msil_microsoft.management.infrastructure_31bf3856ad364e35_7.3.7601.16384_none_8310156aa31a52f1.manifest",
    "msil_microsoft.wsman.runtime_31bf3856ad364e35_7.3.7601.16384_none_a19b148df40272fb.manifest",
    "msil_microsoft.powershell.graphicalhost_31bf3856ad364e35_7.3.7601.16384_none_c32121af2a1808d4.manifest",
    "amd64_microsoft.powershell.psget_31bf3856ad364e35_7.3.7601.16384_none_c9db05c823f10f09.manifest",
    "wow64_microsoft.powershell.psget_31bf3856ad364e35_7.3.7601.16384_none_d42fb01a5851d104.manifest",
    "msil_policy.1.0.system.management.automation_31bf3856ad364e35_7.3.7601.16384_none_79a60ff187b4c325.manifest",
    "wow64_microsoft.windows.powershell.v3.common_31bf3856ad364e35_7.3.7601.16384_none_8187c53a975bb9ea.manifest",
    "amd64_microsoft.windows.powershell.v3.common_31bf3856ad364e35_7.3.7601.16384_none_77331ae862faf7ef.manifest",
    "wow64_microsoft.packagema..provider.powershell_31bf3856ad364e35_7.3.7601.16384_none_f50f549afdaf3c10.manifest",
    "amd64_microsoft.packagema..provider.powershell_31bf3856ad364e35_7.3.7601.16384_none_eabaaa48c94e7a15.manifest",
    "wow64_microsoft.packagema..ement.coreproviders_31bf3856ad364e35_7.3.7601.16384_none_f05cb06fdbbd6e3c.manifest",
    "amd64_microsoft.packagema..ement.coreproviders_31bf3856ad364e35_7.3.7601.16384_none_e608061da75cac41.manifest",
    "amd64_microsoft.packagema..t.archiverproviders_31bf3856ad364e35_7.3.7601.16384_none_a98e3ebb18648eb6.manifest",
    "wow64_microsoft.packagema..t.archiverproviders_31bf3856ad364e35_7.3.7601.16384_none_b3e2e90d4cc550b1.manifest",
    "amd64_microsoft.packagemanagement.msiprovider_31bf3856ad364e35_7.3.7601.16384_none_ae42a045a84e072e.manifest",
    "wow64_microsoft.packagemanagement.msiprovider_31bf3856ad364e35_7.3.7601.16384_none_b8974a97dcaec929.manifest",
    "amd64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_48be7e79e188387e.manifest",
    "wow64_microsoft-windows-powershell-exe_31bf3856ad364e35_7.3.7601.16384_none_531328cc15e8fa79.manifest",
)


def _apply_cfw_ps51_contract(engine_command: str) -> str:
    """Replace broad WMF discovery with CFW's exact, required component set."""
    selector = """python3 - "$payload_root" "$work/manifests.txt" <<'PY'
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
output.write_text("\\n".join(selected) + "\\n", encoding="utf-8")
PY"""
    contract = (
        'cat > "$work/manifests.txt" <<\'CFW_PS51_MANIFESTS\'\n'
        + "\n".join(_CFW_PS51_MANIFESTS)
        + "\nCFW_PS51_MANIFESTS"
    )
    if selector not in engine_command:
        raise RuntimeError("Windows PowerShell 5.1 manifest selector changed unexpectedly")
    engine_command = engine_command.replace(selector, contract, 1)

    required_line = "    required = component.lower() in required_components"
    if required_line not in engine_command:
        raise RuntimeError("Windows PowerShell 5.1 required-component policy changed unexpectedly")
    engine_command = engine_command.replace(required_line, "    required = True", 1)

    engine_command = engine_command.replace(
        'echo "[cage] native mscoree64 bytes=$(wc -c < \\"$native_mscoree64\\" 2>/dev/null || echo 0)"',
        'echo "[cage] native mscoree64 bytes=$(wc -c < "$native_mscoree64" 2>/dev/null || echo 0)"',
        1,
    )
    engine_command = engine_command.replace(
        'echo "[cage] native clr64 bytes=$(wc -c < \\"$native_clr64\\" 2>/dev/null || echo 0)"',
        'echo "[cage] native clr64 bytes=$(wc -c < "$native_clr64" 2>/dev/null || echo 0)"',
        1,
    )
    return engine_command


def windows_powershell51_steps(
    *,
    mscoree_update_url: str | None = None,
    mscoree_update_sha256: str | None = None,
) -> list[BuildStep]:
    """Install the CFW-derived Windows PowerShell 5.1 backend.

    Microsoft servicing CABs do not expose every component payload through
    ordinary 7z extraction. Cage first installs CFW's native AIK DPX helper,
    then restores the native .NET loader that CFW's container finalizer skips,
    and finally materializes the pinned WMF 5.1 components.
    """
    if (mscoree_update_url is None) != (mscoree_update_sha256 is None):
        raise ValueError("native MSCoree URL and sha256 must be supplied together")
    if mscoree_update_url is None or mscoree_update_sha256 is None:
        profile = get_bootstrap_profile()
        mscoree_update_url = profile.mscoree_update_url
        mscoree_update_sha256 = profile.mscoree_update_sha256

    helper_name = "install-dpx-helper.sh"
    loader_name = "install-native-mscoree.sh"
    engine_name = "install-powershell51.sh"
    assembly_name = "assembly_inventory.py"
    assembly_bytes = load_asset_bytes(assembly_name)
    fetch_helper = load_asset("fetch-verified.sh").rstrip()
    loader_command = fetch_helper + "\n\n" + render_asset(
        loader_name,
        {
            "MSCOREE_UPDATE_URL": mscoree_update_url,
            "MSCOREE_UPDATE_SHA256": mscoree_update_sha256,
        },
    )
    engine_command = render_asset(
        engine_name,
        {
            "ASSEMBLY_INVENTORY_PY_BASE64": base64.b64encode(assembly_bytes).decode("ascii"),
            "ASSEMBLY_INVENTORY_PY_SHA256": asset_sha256(assembly_name),
        },
    )
    engine_command = _apply_cfw_ps51_contract(engine_command)
    return [
        BuildStep(
            commands=[load_asset(helper_name)],
            description="Install CFW native DPX extraction helper",
            kind="wine-run",
            timeout=2400,
            metadata={
                "provider": CFW_DPX_PROVIDER,
                "scriptAsset": f"core/chocolatey/assets/{helper_name}",
                "scriptSha256": asset_sha256(helper_name),
                "evidence": "metadata/cfw-dpx-helper.json",
            },
        ),
        BuildStep(
            commands=[loader_command],
            description="Install native .NET MSCoree loader",
            kind="wine-run",
            timeout=900,
            metadata={
                "provider": CFW_MSCOREE_PROVIDER,
                "source": "Windows6.1-KB958488-x64",
                "scriptAsset": f"core/chocolatey/assets/{loader_name}",
                "scriptSha256": asset_sha256(loader_name),
                "evidence": "metadata/native-mscoree.json",
            },
        ),
        BuildStep(
            commands=[engine_command],
            description="Install Windows PowerShell 5.1 backend",
            kind="wine-run",
            timeout=3600,
            metadata={
                "engine": WINDOWS_POWERSHELL_PROVIDER,
                "requires": [CFW_DPX_PROVIDER, CFW_MSCOREE_PROVIDER],
                "scriptAsset": f"core/chocolatey/assets/{engine_name}",
                "scriptSha256": asset_sha256(engine_name),
                "assemblyInventoryAsset": f"core/chocolatey/assets/{assembly_name}",
                "assemblyInventorySha256": asset_sha256(assembly_name),
                "cfwManifestCount": len(_CFW_PS51_MANIFESTS),
                "evidence": "metadata/powershell-engine.json",
            },
        ),
    ]


def powershell_engine_steps(*, wine_prefix: str = "${WINEPREFIX:-$HOME/.wine}", version_slot: str = "7") -> list[BuildStep]:
    """Return the legacy PowerShell Core experiment with strict verification.

    Current Cage Wine runners do not pass this proof, so Chocolatey does not use
    this provider. It remains available only for focused runtime experiments.
    """
    pwsh_dir = f"{wine_prefix}/drive_c/Program Files/PowerShell/{version_slot}"
    pwsh_exe = f"{pwsh_dir}/pwsh.exe"
    script = f"""set -eu
unset WINEDLLOVERRIDES
wine_prefix="{wine_prefix}"
module_cache="${{CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}}"
bundle_root="${{CAGE_BUNDLE_MOUNT:-/opt/cage}}"
engine_logs="$bundle_root/logs/powershell-engine"
engine_metadata="$bundle_root/metadata/powershell-engine.json"
pwsh_cache="$module_cache/powershell"
pwsh_zip="$pwsh_cache/{POWERSHELL_ZIP_NAME}"
pwsh_zip_url="{POWERSHELL_ZIP_URL}"
pwsh_zip_sha256="{POWERSHELL_ZIP_SHA256}"
pwsh_dir="{pwsh_dir}"
pwsh_exe="{pwsh_exe}"
expected_version="{POWERSHELL_VERSION}"
policy_key='HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides'
probe_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
probe_script="$probe_root/engine-probe.ps1"
probe_marker="$probe_root/engine-probe-ok.txt"

mkdir -p "$pwsh_cache" "$engine_logs" "$probe_root" "$(dirname "$engine_metadata")"

prepare_pwsh_policy() {{
  policy_log="$engine_logs/wine-policy.log"
  : > "$policy_log"
  timeout --kill-after=10s 120s winecfg /v win10 >>"$policy_log" 2>&1
  timeout --kill-after=10s 120s wineserver -w >>"$policy_log" 2>&1 || true
  for override in 'amsi=' 'dwmapi=' 'rpcrt4=native,builtin'; do
    name="${{override%%=*}}"
    value="${{override#*=}}"
    timeout --kill-after=10s 120s wine reg add "$policy_key" /v "$name" /d "$value" /f >>"$policy_log" 2>&1
  done
  timeout --kill-after=10s 120s wineserver -w >>"$policy_log" 2>&1 || true
}}

verify_engine() {{
  [ -f "$pwsh_exe" ] || return 1
  chmod +x "$pwsh_exe"
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
  engine_log="$engine_logs/direct-probe.log"
  normalized_log="$engine_logs/direct-probe.normalized.log"
  set +e
  POWERSHELL_TELEMETRY_OPTOUT=1 timeout --kill-after=10s 180s wine "$pwsh_exe" \
    -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File "$probe_script_win" "$probe_marker_win" >"$engine_log" 2>&1
  engine_rc="$?"
  timeout --kill-after=10s 60s wineserver -w >>"$engine_log" 2>&1
  settle_rc="$?"
  tr -d '\r' < "$engine_log" > "$normalized_log"
  grep -Fqx "[cage] engine-version=$expected_version" "$normalized_log"
  stdout_rc="$?"
  if [ -f "$probe_marker" ] && [ "$(tr -d '\r\n' < "$probe_marker")" = "$expected_version" ]; then sentinel_rc=0; else sentinel_rc=1; fi
  set -e
  cat "$normalized_log"
  [ "$engine_rc" -eq 0 ] && [ "$settle_rc" -eq 0 ] && [ "$stdout_rc" -eq 0 ] && [ "$sentinel_rc" -eq 0 ]
}}

prepare_pwsh_policy
if verify_engine; then exit 0; fi
mkdir -p "$pwsh_cache"
if [ ! -f "$pwsh_zip" ]; then curl -fL --retry 3 -o "$pwsh_zip" "$pwsh_zip_url"; fi
actual="$(sha256sum "$pwsh_zip" | cut -d ' ' -f 1)"
[ "$actual" = "$pwsh_zip_sha256" ] || exit 1
rm -rf "$pwsh_dir"
mkdir -p "$pwsh_dir"
python3 - "$pwsh_zip" "$pwsh_dir" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PY
chmod +x "$pwsh_exe"
prepare_pwsh_policy
verify_engine || exit 70"""
    return [BuildStep(
        commands=[script],
        description="Probe experimental PowerShell 7 engine",
        kind="wine-run",
        timeout=1200,
        metadata={
            "engine": f"powershell-zip-{POWERSHELL_VERSION}",
            "experimental": True,
        },
    )]


__all__ = [
    "POWERSHELL_VERSION",
    "POWERSHELL_ZIP_NAME",
    "POWERSHELL_ZIP_URL",
    "POWERSHELL_ZIP_SHA256",
    "WINDOWS_POWERSHELL_PROVIDER",
    "CFW_DPX_PROVIDER",
    "CFW_MSCOREE_PROVIDER",
    "windows_powershell51_steps",
    "powershell_engine_steps",
]
