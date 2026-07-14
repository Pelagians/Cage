from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


install_path = Path("core/chocolatey/assets/install-powershell51.sh")
install = install_path.read_text(encoding="utf-8")
install = replace_once(
    install,
    '''assembly_exe="$work/assembly-inventory.exe"
assembly_map="$work/assembly-inventory.tsv"
assembly_asset_log="$log_root/assembly-inventory-asset.log"
assembly_run_log="$log_root/assembly-inventory-run.log"
gac_log="$log_root/gac-installs.log"
assembly_exe_sha256="{{ASSEMBLY_INVENTORY_EXE_SHA256}}"
''',
    '''assembly_script="$work/assembly_inventory.py"
assembly_map="$work/assembly-inventory.tsv"
assembly_asset_log="$log_root/assembly-inventory-asset.log"
assembly_run_log="$log_root/assembly-inventory-run.log"
gac_log="$log_root/gac-installs.log"
assembly_script_sha256="{{ASSEMBLY_INVENTORY_PY_SHA256}}"
''',
    "inventory variables",
)

start = install.find("materialize_assembly_inventory() {")
end = install.find("write_engine_metadata() {", start)
if start < 0 or end < 0:
    raise SystemExit("missing materialize_assembly_inventory block")
replacement = r'''materialize_assembly_inventory() {
  rm -f "$assembly_script" "$assembly_script.part" "$assembly_map"
  base64 -d > "$assembly_script.part" <<'B64'
{{ASSEMBLY_INVENTORY_PY_BASE64}}
B64
  actual_sha256="$(sha256sum "$assembly_script.part" | cut -d ' ' -f 1)"
  {
    echo "expected=$assembly_script_sha256"
    echo "actual=$actual_sha256"
  } > "$assembly_asset_log"
  if [ "$actual_sha256" != "$assembly_script_sha256" ]; then
    echo "[cage] ERROR: assembly inventory script checksum mismatch" >&2
    exit 69
  fi
  chmod 0644 "$assembly_script.part"
  mv -f "$assembly_script.part" "$assembly_script"

  python3 "$assembly_script" "$payload_root" "$assembly_map" \
    > "$assembly_run_log" 2>&1
  test -s "$assembly_map"
}

'''
install = install[:start] + replacement + install[end:]
install_path.write_text(install, encoding="utf-8")

module_path = Path("core/modules/powershell_engine.py")
module = module_path.read_text(encoding="utf-8")
module = replace_once(
    module,
    'assembly_name = "assembly-inventory.exe"',
    'assembly_name = "assembly_inventory.py"',
    "asset name",
)
module = replace_once(
    module,
    '"ASSEMBLY_INVENTORY_EXE_BASE64": base64.b64encode(assembly_bytes).decode("ascii"),\n            "ASSEMBLY_INVENTORY_EXE_SHA256": asset_sha256(assembly_name),',
    '"ASSEMBLY_INVENTORY_PY_BASE64": base64.b64encode(assembly_bytes).decode("ascii"),\n            "ASSEMBLY_INVENTORY_PY_SHA256": asset_sha256(assembly_name),',
    "render tokens",
)
module_path.write_text(module, encoding="utf-8")

pyproject_path = Path("pyproject.toml")
pyproject = pyproject_path.read_text(encoding="utf-8")
pyproject = replace_once(
    pyproject,
    '"core.chocolatey.assets" = ["*.sh", "*.ps1", "*.nupkg", "*.exe", "*.cs"]',
    '"core.chocolatey.assets" = ["*.sh", "*.ps1", "*.nupkg", "*.py"]',
    "package data",
)
pyproject_path.write_text(pyproject, encoding="utf-8")

print("patched PS5.1 assembly inventory to pure Python")
