set -eu
echo "[cage] Install native .NET loader"
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
cache_root="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
bootstrap_dir="$cache_root/bootstrap/{{BOOTSTRAP_PROFILE_ID}}"
msu="$bootstrap_dir/windows6.1-kb958488-x64.msu"
work="$bootstrap_dir/kb958488"
metadata="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-mscoree.json"
mkdir -p "$bootstrap_dir" "$(dirname "$metadata")"
cage_fetch_verified '{{MSCOREE_UPDATE_URL}}' '{{MSCOREE_UPDATE_SHA256}}' "$msu" '{{BOOTSTRAP_PROFILE_ID}}'
rm -rf "$work"
mkdir -p "$work/outer" "$work/payload"
7z x -y -o"$work/outer" "$msu" 'Windows6.1-KB958488-x64.cab' >/dev/null
cab="$work/outer/Windows6.1-KB958488-x64.cab"
if [ ! -f "$cab" ]; then
  echo "[cage] ERROR: KB958488 inner CAB missing" >&2
  exit 66
fi
7z x -y -o"$work/payload" "$cab" >/dev/null
python3 - "$work/payload" "$wine_prefix/drive_c" "$metadata" '{{MSCOREE_UPDATE_SHA256}}' <<'PY'
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

payload = Path(sys.argv[1])
drive_c = Path(sys.argv[2])
metadata = Path(sys.argv[3])
source_sha256 = sys.argv[4]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pe_machine(path: Path) -> int:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise SystemExit(f"native mscoree source is not PE: {path}")
        stream.seek(0x3C)
        pe_offset_raw = stream.read(4)
        if len(pe_offset_raw) != 4:
            raise SystemExit(f"native mscoree PE header is truncated: {path}")
        pe_offset = struct.unpack("<I", pe_offset_raw)[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise SystemExit(f"native mscoree PE signature missing: {path}")
        machine_raw = stream.read(2)
        if len(machine_raw) != 2:
            raise SystemExit(f"native mscoree PE machine is truncated: {path}")
        return struct.unpack("<H", machine_raw)[0]

files = [
    path for path in payload.rglob("*")
    if path.is_file() and str(path.relative_to(payload)).replace("\\", "/").lower().endswith("/mscoree.dll")
]
selectors = {
    "x64": ("amd64_netfx-mscoree_dll_", 0x8664, drive_c / "windows/system32/mscoree.dll"),
    "x86": ("x86_netfx-mscoree_dll_", 0x014C, drive_c / "windows/syswow64/mscoree.dll"),
}
installed = []
for architecture, (component, expected_machine, destination) in selectors.items():
    matches = [
        path for path in files
        if str(path.relative_to(payload)).replace("\\", "/").lower().startswith(component)
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"expected exactly one {architecture} native mscoree source, found {len(matches)}: "
            + ", ".join(str(path) for path in matches)
        )
    source = matches[0]
    actual_machine = pe_machine(source)
    if actual_machine != expected_machine:
        raise SystemExit(
            f"native mscoree architecture mismatch for {source}: "
            f"0x{actual_machine:04x} != 0x{expected_machine:04x}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    shutil.copy2(source, temporary)
    temporary.replace(destination)
    installed.append({
        "architecture": architecture,
        "machine": f"0x{actual_machine:04x}",
        "source": str(source.relative_to(payload)).replace("\\", "/"),
        "destination": "C:/" + str(destination.relative_to(drive_c)).replace("\\", "/"),
        "sha256": sha256_file(destination),
        "size": destination.stat().st_size,
    })

record = {
    "schemaVersion": "cage.chocolatey-mscoree/v0",
    "status": "installed",
    "source": {
        "url": "{{MSCOREE_UPDATE_URL}}",
        "sha256": source_sha256,
        "upstreamSha1": "a137e4f328f01146dfa75d7b5a576090dee948dc",
    },
    "files": installed,
}
temporary = metadata.with_suffix(metadata.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(metadata)
PY
rm -rf "$work"
echo "[cage] Native .NET loader installed"
