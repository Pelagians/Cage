set -eu
unset WINEDLLOVERRIDES
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
# Stable Windows destination: C:/ProgramData/Cage/PowerShell/profile.d
profile_root="$wine_prefix/drive_c/ProgramData/Cage/PowerShell"
fragment_dir="$profile_root/profile.d"
cfw_root="$wine_prefix/drive_c/ProgramData/Chocolatey-for-wine"
metadata_dir="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata"
contract_commit="{{CFW_CONTRACT_COMMIT}}"

profile="$wine_prefix/drive_c/Program Files/PowerShell/7/profile.ps1"
synchro_fragment="$fragment_dir/10-synchro.ps1"
test -s "$profile"
test -s "$synchro_fragment"
mkdir -p "$fragment_dir" "$cfw_root/command-adapters" "$metadata_dir"

write_fragment() {
  destination="$1"
  encoded="$2"
  temporary="$destination.part"
  printf '%s' "$encoded" | base64 -d > "$temporary"
  test -s "$temporary"
  mv -f "$temporary" "$destination"
}

write_fragment "$fragment_dir/20-chocolatey.ps1" "{{PROFILE_20_B64}}"
write_fragment "$fragment_dir/30-cfw-winetricks.ps1" "{{PROFILE_30_B64}}"
write_fragment "$fragment_dir/40-cfw-command-adapters.ps1" "{{PROFILE_40_B64}}"

python3 - "$metadata_dir/powershell-profile-composition.json" "$contract_commit" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
commit = sys.argv[2]
record = {
    "schemaVersion": "cage.powershell-profile-composition/v1",
    "owner": "cage",
    "synchroProvider": "v4.2.0",
    "cfwContractCommit": commit,
    "orderedFragments": [
        "10-synchro.ps1",
        "20-chocolatey.ps1",
        "30-cfw-winetricks.ps1",
        "40-cfw-command-adapters.ps1",
    ],
}
temporary = output.with_suffix(output.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(output)
PY

for fragment in \
  "$fragment_dir/10-synchro.ps1" \
  "$fragment_dir/20-chocolatey.ps1" \
  "$fragment_dir/30-cfw-winetricks.ps1" \
  "$fragment_dir/40-cfw-command-adapters.ps1"; do
  test -s "$fragment"
  sha256sum "$fragment"
done

echo "[cage] Installed ordered Synchro and CFW PowerShell profile fragments"
