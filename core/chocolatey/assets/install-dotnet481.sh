# Frozen compatibility profile: dotnet481-cfw-r1
set -eu
unset WINEDLLOVERRIDES
wine_prefix="${WINEPREFIX:-$HOME/.wine}"
module_cache="${CAGE_MODULE_CACHE_DIR:-/tmp/cage-module-cache}"
dotnet_cache="$module_cache/dotnet481"
ndp481_exe="$dotnet_cache/ndp481-x86-x64-allos-enu.exe"
ndp481_url="{{DOTNET_INSTALLER_URL}}"
ndp481_sha256="{{DOTNET_INSTALLER_SHA256}}"
dotnet_extract="$dotnet_cache/extracted"
dotnet_payload="$dotnet_cache/dotnet481_manifest_payload"
dotnet_cab="$dotnet_extract/x64-Windows10.0-KB5011048-x64.cab"
reg_dir="$wine_prefix/drive_c/windows/temp"
dotnet_profile_manifest="${CAGE_BUNDLE_MOUNT:-/opt/cage}/metadata/chocolatey-dotnet-profile.json"
mkdir -p "$dotnet_cache" "$dotnet_extract" "$reg_dir" "$(dirname "$dotnet_profile_manifest")"
echo "[cage] Resolving upstream .NET Framework 4.8.1 payload from verified cache..."
cage_fetch_verified "$ndp481_url" "$ndp481_sha256" "$ndp481_exe" "{{BOOTSTRAP_PROFILE_ID}}"
actual_ndp481_sha="$(sha256sum "$ndp481_exe" | cut -d ' ' -f 1)"
if [ "$actual_ndp481_sha" != "$ndp481_sha256" ]; then
  echo "[cage] ERROR: .NET Framework 4.8.1 installer checksum mismatch"
  echo "[cage]   expected: $ndp481_sha256"
  echo "[cage]   actual:   $actual_ndp481_sha"
  exit 1
fi
extractor=""
for candidate in 7z 7zz 7za; do
  if command -v "$candidate" >/dev/null 2>&1; then
    extractor="$candidate"
    break
  fi
done
if [ -z "$extractor" ]; then
  echo "[cage] ERROR: 7z/7zz/7za is required for upstream dotnet481 manifest extraction"
  exit 1
fi
if [ ! -f "$dotnet_cab" ]; then
  rm -rf "$dotnet_extract"
  mkdir -p "$dotnet_extract"
  echo "[cage] Extracting upstream dotnet481 Windows cab..."
  "$extractor" x -y "$ndp481_exe" "-o$dotnet_extract" "x64-Windows10.0-KB5011048-x64.cab"
fi
test -f "$dotnet_cab"
rm -rf "$dotnet_payload"
mkdir -p "$dotnet_payload"
echo "[cage] Extracting upstream dotnet481 manifests and native payload..."
"$extractor" x -y "$dotnet_cab" "-o$dotnet_payload" "amd64*/*" "x86*/*" "wow64*/*" "*.manifest"

python3 - "$dotnet_payload" "$wine_prefix/drive_c" "$reg_dir" "$dotnet_profile_manifest" "{{DOTNET_PROFILE}}" "$actual_ndp481_sha" <<'PY'
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

payload = Path(sys.argv[1])
drive_c = Path(sys.argv[2])
reg_dir = Path(sys.argv[3])
profile_manifest = Path(sys.argv[4])
profile_id = sys.argv[5]
source_installer_sha256 = sys.argv[6]
windows = drive_c / "windows"
copied_files = []
reg_dir.mkdir(parents=True, exist_ok=True)

reg64 = reg_dir / "reg_keys64.reg"
reg32 = reg_dir / "reg_keys32.reg"
reg64.write_text("Windows Registry Editor Version 5.00\n", encoding="utf-8")
reg32.write_text("Windows Registry Editor Version 5.00\n", encoding="utf-8")

TOKEN_MAP_64 = dict([
    ("$(runtime.system32)", "C:/windows/system32"),
    ("$(runtime.programFiles)", "C:/Program Files"),
    ("$(runtime.commonFiles)", "C:/Program Files/Common Files"),
    ("$(runtime.wbem)", "C:/windows/system32/wbem"),
    ("$(runtime.windows)", "C:/windows"),
    ("$(runtime.inf)", "C:/windows/inf"),
])
TOKEN_MAP_32 = dict([
    ("$(runtime.system32)", "C:/windows/syswow64"),
    ("$(runtime.programFiles)", "C:/Program Files (x86)"),
    ("$(runtime.commonFiles)", "C:/Program Files (x86)/Common Files"),
    ("$(runtime.wbem)", "C:/windows/syswow64/wbem"),
    ("$(runtime.windows)", "C:/windows"),
    ("$(runtime.inf)", "C:/windows/inf"),
])

def tag_name(element):
    return element.tag.rsplit("}", 1)[-1]


def children(element, name):
    return [child for child in list(element) if tag_name(child).lower() == name.lower()]


def first_child_text(element, *names):
    wanted = {name.lower() for name in names}
    for child in list(element):
        if tag_name(child).lower() in wanted and child.text:
            return child.text
    return None


def attr(element, *names):
    wanted = {name.lower() for name in names}
    for key, value in element.attrib.items():
        if key.lower() in wanted:
            return value
    return None


def arch(root):
    identities = children(root, "assemblyIdentity")
    value = attr(identities[0], "processorArchitecture") if identities else "amd64"
    return (value or "amd64").lower()


def token_map_for(arch_value):
    return TOKEN_MAP_32 if arch_value in {"x86", "wow64"} else TOKEN_MAP_64


def replace_tokens(value, arch_value):
    if value is None:
        return value
    assembly_empty_sentinel = "__CAGE_ASSEMBLY_EMPTY__"
    result = value.replace("$$(assembly.empty)", assembly_empty_sentinel)
    for token, replacement in token_map_for(arch_value).items():
        result = result.replace(token, replacement)
    unknown = sorted(set(re.findall(r"\$\([^)]+\)", result)))
    if unknown:
        raise SystemExit("unknown required manifest token: " + ", ".join(unknown))
    result = result.replace(assembly_empty_sentinel, "$")
    return result.replace("/", chr(92))


def win_to_host(path):
    bs = chr(92)
    value = path.replace("/", bs)
    if value.lower().startswith("c:" + bs):
        value = value[3:]
    value = value.lstrip(bs)
    parts = [part for part in value.split(bs) if part]
    return drive_c.joinpath(*parts)


def source_dir_for(manifest):
    return Path(str(manifest)[: -len(".manifest")])


def find_file(directory, name):
    direct = directory / name
    if direct.is_file():
        return direct
    lower = name.lower()
    local_matches = []
    if directory.exists():
        local_matches = [
            candidate for candidate in directory.iterdir()
            if candidate.is_file() and candidate.name.lower() == lower
        ]
    if len(local_matches) == 1:
        return local_matches[0]
    if len(local_matches) > 1:
        raise SystemExit(f"ambiguous dotnet481 source for {name}: " + ", ".join(map(str, local_matches)))
    matches = [
        candidate for candidate in payload.rglob("*")
        if candidate.is_file() and candidate.name.lower() == lower
    ]
    if not matches:
        raise SystemExit(f"missing required dotnet481 source: {name}")
    if len(matches) > 1:
        raise SystemExit(f"ambiguous dotnet481 source for {name}: " + ", ".join(map(str, matches)))
    return next(iter(matches))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    copied_files.append({
        "source": str(src),
        "destination": "C:/" + str(dest.relative_to(drive_c)).replace(chr(92), "/"),
        "sha256": sha256_file(dest),
    })


def destination_paths(file_element):
    values = []
    for key in ("destinationPath", "destinationpath"):
        value = attr(file_element, key)
        if value:
            values.append(value)
    for child in list(file_element):
        if tag_name(child).lower() == "destinationpath" and child.text:
            values.append(child.text)
        if tag_name(child).lower() == "link":
            for grandchild in list(child):
                if tag_name(grandchild).lower() == "destination" and grandchild.text:
                    values.append(grandchild.text)
    return values


def install_manifest_files(manifest):
    root = ET.parse(manifest).getroot()
    arch_value = arch(root)
    source_dir = source_dir_for(manifest)
    copied = 0
    for file_element in children(root, "file"):
        name = attr(file_element, "name")
        if not name:
            continue
        src = find_file(source_dir, name)
        destinations = destination_paths(file_element)
        if not destinations:
            raise SystemExit(f"missing required dotnet481 destination for {name} in {manifest}")
        for destination in destinations:
            destination_dir = win_to_host(replace_tokens(destination, arch_value))
            final = destination_dir / name
            copy_file(src, final)
            copied += 1
    return copied


def reg_file_for(arch_value):
    return reg32 if arch_value in {"x86", "wow64"} else reg64


def reg_escape(value):
    bs = chr(92)
    return value.replace(bs, bs + bs).replace('"', bs + '"')


def hex_bytes(data):
    return ",".join(f"{byte:02x}" for byte in data)


def format_reg_value(kind, value):
    kind = (kind or "REG_SZ").upper()
    value = value or ""
    if kind == "REG_DWORD":
        number = int(value, 0) if value else 0
        return f"dword:{number:08x}"
    if kind == "REG_BINARY":
        compact = re.sub(r"[^0-9A-Fa-f]", "", value)
        return "hex:" + ",".join(compact[i : i + 2] for i in range(0, len(compact), 2))
    if kind == "REG_EXPAND_SZ":
        return "hex(2):" + hex_bytes((value + chr(0)).encode("utf-16le"))
    if kind == "REG_MULTI_SZ":
        return "hex(7):" + hex_bytes((value + chr(0) + chr(0)).encode("utf-16le"))
    if kind == "REG_QWORD":
        number = int(value, 0) if value else 0
        return "hex(b):" + hex_bytes(number.to_bytes(8, "little"))
    if kind == "REG_NONE":
        return '""'
    return f'"{reg_escape(value)}"'


def write_manifest_registry(manifest):
    root = ET.parse(manifest).getroot()
    arch_value = arch(root)
    output = reg_file_for(arch_value)
    blocks = []
    for registry_keys in children(root, "registryKeys"):
        for key in children(registry_keys, "registryKey"):
            key_name = attr(key, "keyName")
            if not key_name:
                continue
            key_name = replace_tokens(key_name, arch_value)
            lines = ["", f"[{key_name}]"]
            for value in children(key, "registryValue"):
                name = attr(value, "name", "Name") or ""
                reg_name = "@" if name in {"", "registryValue"} else f'"{reg_escape(replace_tokens(name, arch_value))}"'
                reg_value = replace_tokens(attr(value, "value", "Value") or first_child_text(value, "value") or "", arch_value)
                reg_type = attr(value, "valueType", "type") or "REG_SZ"
                lines.append(f"{reg_name}={format_reg_value(reg_type, reg_value)}")
            blocks.append("\n".join(lines))
    if blocks:
        with output.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(blocks) + "\n")


def copy_first(name, destination, preferred_prefixes):
    candidates = []
    lower = name.lower()
    for candidate in payload.rglob("*"):
        if candidate.is_file() and candidate.name.lower() == lower:
            score = len(preferred_prefixes) + 1
            text = str(candidate).lower()
            for index, prefix in enumerate(preferred_prefixes):
                if prefix in text:
                    score = index
                    break
            candidates.append((score, candidate))
    if not candidates:
        raise SystemExit(f"missing required dotnet481 source: {name}")
    best_score = min(score for score, _ in candidates)
    best = sorted(candidate for score, candidate in candidates if score == best_score)
    if len(best) != 1:
        raise SystemExit(f"ambiguous dotnet481 source for {name}: " + ", ".join(map(str, best)))
    copy_file(best[0], destination)
    return True

framework64 = windows / "Microsoft.NET" / "Framework64" / "v4.0.30319"
framework32 = windows / "Microsoft.NET" / "Framework" / "v4.0.30319"
old_mscoreei = framework64 / "mscoreei_old.dll"
current_mscoreei = framework64 / "mscoreei.dll"
if current_mscoreei.exists() and not old_mscoreei.exists():
    old_mscoreei.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_mscoreei, old_mscoreei)

manifests = sorted(payload.glob("*.manifest"))
if not manifests:
    raise SystemExit(f"no dotnet481 manifests extracted under {payload}")
file_count = 0
for manifest in manifests:
    file_count += install_manifest_files(manifest)
    write_manifest_registry(manifest)

# Keep the native CLR loader files explicit even if a manifest uses a path form
# this parser does not understand. These are the files Wine must load before
# managed Chocolatey can emit any output.
required_copies = [
    ("mscoree.dll", windows / "system32" / "mscoree.dll", ("amd64",)),
    ("mscoree.dll", windows / "syswow64" / "mscoree.dll", ("x86", "wow64")),
    ("mscoreei.dll", framework64 / "mscoreei.dll", ("amd64",)),
    ("mscoreei.dll", framework32 / "mscoreei.dll", ("x86", "wow64")),
    ("clr.dll", framework64 / "clr.dll", ("amd64",)),
    ("clr.dll", framework32 / "clr.dll", ("x86", "wow64")),
    ("clrjit.dll", framework64 / "clrjit.dll", ("amd64",)),
    ("clrjit.dll", framework32 / "clrjit.dll", ("x86", "wow64")),
    ("ucrtbase_clr0400.dll", windows / "system32" / "ucrtbase_clr0400.dll", ("amd64",)),
    ("ucrtbase_clr0400.dll", windows / "syswow64" / "ucrtbase_clr0400.dll", ("x86", "wow64")),
    ("vcruntime140_clr0400.dll", windows / "system32" / "vcruntime140_clr0400.dll", ("amd64",)),
    ("vcruntime140_clr0400.dll", windows / "syswow64" / "vcruntime140_clr0400.dll", ("x86", "wow64")),
]
missing_sources = []
for name, destination, prefixes in required_copies:
    if not copy_first(name, destination, prefixes):
        missing_sources.append(name)
if missing_sources:
    raise SystemExit("missing upstream dotnet481 native files: " + ", ".join(sorted(set(missing_sources))))

required_markers = [
    windows / "system32" / "mscoree.dll",
    windows / "syswow64" / "mscoree.dll",
    framework64 / "clr.dll",
    framework64 / "clrjit.dll",
    framework64 / "mscoreei.dll",
    framework32 / "clr.dll",
    framework32 / "mscoreei.dll",
    windows / "system32" / "ucrtbase_clr0400.dll",
    windows / "system32" / "vcruntime140_clr0400.dll",
]
missing = [str(path) for path in required_markers if not path.is_file()]
if missing:
    raise SystemExit("missing upstream dotnet481 marker files: " + ", ".join(missing))
install_record = {
    "schemaVersion": "cage.chocolatey-dotnet-profile/v0",
    "profile": profile_id,
    "status": "files-copied",
    "sourceInstallerSha256": source_installer_sha256,
    "manifestCount": len(manifests),
    "copiedFileCount": len(copied_files),
    "copiedFiles": copied_files,
    "registryImports": [
        {"view": "64", "path": "C:/windows/temp/reg_keys64.reg", "sha256": sha256_file(reg64)},
        {"view": "32", "path": "C:/windows/temp/reg_keys32.reg", "sha256": sha256_file(reg32)},
    ],
}
temporary = profile_manifest.with_suffix(profile_manifest.suffix + ".part")
temporary.write_text(json.dumps(install_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(profile_manifest)
print(f"installed dotnet481 manifest payload: manifests={len(manifests)} files={file_count}")
PY

# Import manifest-derived registry keys exactly through Wine's 64-bit and 32-bit views.
wine reg IMPORT 'c:\windows\temp\reg_keys64.reg' /reg:64
wine reg IMPORT 'c:\windows\temp\reg_keys32.reg' /reg:32
python3 - "$dotnet_profile_manifest" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
record = json.loads(path.read_text(encoding="utf-8"))
record["status"] = "installed"
temporary = path.with_suffix(path.suffix + ".part")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY

dotnet_mscoree_marker_x86="$wine_prefix/drive_c/windows/syswow64/mscoree.dll"
dotnet_clr_marker_x86="$wine_prefix/drive_c/windows/Microsoft.NET/Framework/v4.0.30319/clr.dll"
dotnet_mscoree_marker_x64="$wine_prefix/drive_c/windows/system32/mscoree.dll"
dotnet_clr_marker_x64="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll"
dotnet_clrjit_marker_x64="$wine_prefix/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clrjit.dll"
for marker in "$dotnet_mscoree_marker_x86" "$dotnet_clr_marker_x86" "$dotnet_mscoree_marker_x64" "$dotnet_clr_marker_x64" "$dotnet_clrjit_marker_x64"; do
  if [ ! -f "$marker" ]; then
    echo "[cage] ERROR: upstream dotnet481 marker missing after manifest install: $marker"
    exit 67
  fi
done
echo "[cage] Upstream dotnet481 manifest payload installed for Chocolatey"
