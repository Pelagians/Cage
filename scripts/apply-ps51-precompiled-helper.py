from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


install_path = Path("core/chocolatey/assets/install-powershell51.sh")
install = install_path.read_text(encoding="utf-8")
install = replace_once(
    install,
    '''failure_trace="$log_root/direct-probe-winedebug.log"
assembly_source="$work/assembly-inventory.cs"
assembly_exe="$work/assembly-inventory.exe"
assembly_map="$work/assembly-inventory.tsv"
assembly_compile_log="$log_root/assembly-inventory-compile.log"
assembly_run_log="$log_root/assembly-inventory-run.log"
gac_log="$log_root/gac-installs.log"
''',
    '''failure_trace="$log_root/direct-probe-winedebug.log"
assembly_exe="$work/assembly-inventory.exe"
assembly_map="$work/assembly-inventory.tsv"
assembly_asset_log="$log_root/assembly-inventory-asset.log"
assembly_run_log="$log_root/assembly-inventory-run.log"
gac_log="$log_root/gac-installs.log"
assembly_exe_sha256="{{ASSEMBLY_INVENTORY_EXE_SHA256}}"
''',
    "assembly variables",
)

start = install.find("write_assembly_inventory_helper() {")
end = install.find("write_engine_metadata() {", start)
if start < 0 or end < 0:
    raise SystemExit("missing assembly helper function block")
materialize = r'''materialize_assembly_inventory() {
  rm -f "$assembly_exe" "$assembly_exe.part" "$assembly_map"
  base64 -d > "$assembly_exe.part" <<'B64'
{{ASSEMBLY_INVENTORY_EXE_BASE64}}
B64
  actual_sha256="$(sha256sum "$assembly_exe.part" | cut -d ' ' -f 1)"
  {
    echo "expected=$assembly_exe_sha256"
    echo "actual=$actual_sha256"
  } > "$assembly_asset_log"
  if [ "$actual_sha256" != "$assembly_exe_sha256" ]; then
    echo "[cage] ERROR: assembly inventory helper checksum mismatch" >&2
    exit 69
  fi
  chmod 0755 "$assembly_exe.part"
  mv -f "$assembly_exe.part" "$assembly_exe"

  payload_win_for_inventory="$(winepath -w "$payload_root")"
  map_win="$(winepath -w "$assembly_map")"
  timeout --kill-after=10s 240s wine "$assembly_exe" "$payload_win_for_inventory" "$map_win" \
    > "$assembly_run_log" 2>&1
  test -s "$assembly_map"
}

'''
install = install[:start] + materialize + install[end:]
install = replace_once(
    install,
    '        "assemblyInventoryCompile": "logs/powershell-engine/assembly-inventory-compile.log",\n',
    '        "assemblyInventoryAsset": "logs/powershell-engine/assembly-inventory-asset.log",\n',
    "metadata asset log",
)
install = replace_once(
    install,
    'build_assembly_inventory\n',
    'materialize_assembly_inventory\n',
    "materialize call",
)
install_path.write_text(install, encoding="utf-8")

module_path = Path("core/modules/powershell_engine.py")
module = module_path.read_text(encoding="utf-8")
module = replace_once(
    module,
    'from __future__ import annotations\n\nfrom core.chocolatey import asset_sha256, load_asset\n',
    'from __future__ import annotations\n\nimport base64\n\nfrom core.chocolatey import (\n    asset_sha256,\n    load_asset,\n    load_asset_bytes,\n    render_asset,\n)\n',
    "module imports",
)
module = replace_once(
    module,
    '    helper_name = "install-dpx-helper.sh"\n    engine_name = "install-powershell51.sh"\n    return [\n',
    '    helper_name = "install-dpx-helper.sh"\n    engine_name = "install-powershell51.sh"\n    assembly_name = "assembly-inventory.exe"\n    assembly_bytes = load_asset_bytes(assembly_name)\n    engine_command = render_asset(\n        engine_name,\n        {\n            "ASSEMBLY_INVENTORY_EXE_BASE64": base64.b64encode(assembly_bytes).decode("ascii"),\n            "ASSEMBLY_INVENTORY_EXE_SHA256": asset_sha256(assembly_name),\n        },\n    )\n    return [\n',
    "rendered engine command",
)
module = replace_once(
    module,
    '            commands=[load_asset(engine_name)],\n            description="Install Windows PowerShell 5.1 backend",\n',
    '            commands=[engine_command],\n            description="Install Windows PowerShell 5.1 backend",\n',
    "engine command",
)
module = replace_once(
    module,
    '                "scriptSha256": asset_sha256(engine_name),\n                "evidence": "metadata/powershell-engine.json",\n',
    '                "scriptSha256": asset_sha256(engine_name),\n                "assemblyInventoryAsset": f"core/chocolatey/assets/{assembly_name}",\n                "assemblyInventorySha256": asset_sha256(assembly_name),\n                "evidence": "metadata/powershell-engine.json",\n',
    "engine metadata",
)
module_path.write_text(module, encoding="utf-8")

pyproject_path = Path("pyproject.toml")
pyproject = pyproject_path.read_text(encoding="utf-8")
pyproject = replace_once(
    pyproject,
    '"core.chocolatey.assets" = ["*.sh", "*.ps1", "*.nupkg"]',
    '"core.chocolatey.assets" = ["*.sh", "*.ps1", "*.nupkg", "*.exe", "*.cs"]',
    "package data",
)
pyproject_path.write_text(pyproject, encoding="utf-8")

print("patched precompiled PS5.1 assembly helper integration")
