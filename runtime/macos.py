"""Pinned Darwin Wine acquisition and verification, shared by native targets and CI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request

from runtime.desktop_launch import DesktopError, inventory_tree, digest_json

LOCK = Path(__file__).with_name("macos-metalsharp-v2.0.json")


def runtime_target():
    return json.loads(LOCK.read_text())


def require_host():
    target = runtime_target()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise DesktopError("native macOS target requires Apple Silicon macOS; Linux/Asahi uses its existing runtime")
    if os.sysconf("SC_PAGE_SIZE") not in target["hostPageSizes"]:
        raise DesktopError("native macOS runtime has not qualified this host page size")
    version = tuple(int(n) for n in platform.mac_ver()[0].split(".")[:2])
    if version < (15, 0):
        raise DesktopError("pinned native runtime requires macOS 15 or newer")


def store_path(store=None):
    return Path(store).absolute() if store else Path.home() / "Library/Caches/Cage/metalsharp-v2.0"


def verify_runtime(store):
    """Bind every consumed runtime byte to the previously qualified payload."""
    target = runtime_target()
    store = store_path(store)
    if store.is_symlink():
        raise DesktopError("linked macOS runtime store rejected")
    runtime = store / target["runtimeDirectory"]
    if digest_json(inventory_tree(runtime)) != target["payloadDigest"]:
        raise DesktopError("macOS runtime inventory mismatch; cached runtime and application state retained")
    return runtime


def ensure_runtime(store=None):
    require_host()
    target, store = runtime_target(), store_path(store)
    if store.exists() or store.is_symlink():
        return verify_runtime(store)
    store.mkdir(parents=True)
    downloads, evidence = store / "downloads", store / "verification"
    downloads.mkdir(); evidence.mkdir()
    archive = provenance(target, downloads, evidence)
    extract_runtime(archive, store, target["runtimeDirectory"], evidence)
    runtime = verify_runtime(store)
    audit_macho(runtime, evidence)
    write(evidence / "runtime-seal.json", {"targetDigest": digest_json(target), "payloadDigest": target["payloadDigest"]})
    return runtime


def execution_environment(runtime, prefix, home):
    environment = {key: value for key, value in os.environ.items()
                   if key in {"USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}}
    environment.update(runtime_target()["environment"], WINEPREFIX=str(Path(prefix).absolute()),
                       HOME=str(Path(home).absolute()), TMPDIR=str(Path(home).absolute() / "tmp"),
                       PATH=str(runtime / "bin") + ":/usr/bin:/bin:/usr/sbin:/sbin")
    return environment


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")



def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def download(url, path, expected, limit):
    """Authenticate the actual bytes consumed, including existing cached bytes."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("linked download rejected")
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "Cage-macOS-runtime-proof"})
        partial = path.with_name(path.name + ".partial")
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("xb") as output:
            if not response.url.startswith("https://"):
                raise ValueError("download redirect left HTTPS")
            total = 0
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                total += len(chunk)
                if total > limit:
                    raise ValueError("download exceeds quota")
                output.write(chunk)
        partial.rename(path)
    if not path.is_file() or path.stat().st_size > limit or sha256(path) != expected:
        raise ValueError("download checksum mismatch: " + path.name)
    return path



def api(path):
    headers = {"User-Agent": "Cage-macOS-runtime-proof", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request("https://api.github.com/" + path, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)



def verify_metadata(lock, release, commit, tree, tag):
    """Fail on moved releases/tags, changed asset bytes or source gitlinks."""
    if (release["id"] != lock["releaseId"] or release["tag_name"] != lock["tag"]
            or release.get("draft") or release.get("prerelease")
            or commit["sha"] != lock["sourceCommit"]
            or commit["commit"]["tree"]["sha"] != lock["sourceTree"]
            or tree["sha"] != lock["sourceTree"] or tree.get("truncated")
            or tag != {"type": "commit", "sha": lock["sourceCommit"]}):
        raise ValueError("publisher release/source identity mismatch")
    members = {item["path"]: item for item in tree["tree"]}
    for path, pin in lock["sourcePins"].items():
        if members.get(path, {}).get("sha") != pin or members[path].get("type") != "commit":
            raise ValueError("producer source pin mismatch: " + path)
    assets = {item["name"]: item for item in release["assets"]}
    for spec in (lock["asset"], lock["checksums"]):
        actual = assets[spec["name"]]
        url = f"https://github.com/{lock['repository']}/releases/download/{lock['tag']}/{spec['name']}"
        if (actual["size"] != spec["size"] or actual["digest"] != "sha256:" + spec["sha256"]
                or actual["browser_download_url"] != url or spec.get("id", actual["id"]) != actual["id"]):
            raise ValueError("publisher asset identity mismatch: " + spec["name"])



def provenance(lock, downloads, evidence):
    repo = "repos/" + lock["repository"]
    release = api(repo + "/releases/" + str(lock["releaseId"]))
    commit = api(repo + "/commits/" + lock["sourceCommit"])
    tree = api(repo + "/git/trees/" + lock["sourceTree"] + "?recursive=1")
    tag = api(repo + "/git/ref/tags/" + lock["tag"])["object"]
    while tag["type"] == "tag":
        tag = api(repo + "/git/tags/" + tag["sha"])["object"]
    verify_metadata(lock, release, commit, tree, {key: tag[key] for key in ("type", "sha")})
    for name, data in (("release", release), ("source-commit", commit), ("source-tree", tree)):
        write(evidence / (name + ".json"), data)
    base = f"https://github.com/{lock['repository']}/releases/download/{lock['tag']}/"
    checksums = download(base + lock["checksums"]["name"], downloads / "SHA256SUMS",
                         lock["checksums"]["sha256"], 4096)
    expected = lock["asset"]["sha256"] + "  " + lock["asset"]["name"]
    if expected not in checksums.read_text().splitlines():
        raise ValueError("publisher checksum manifest does not bind the runtime")
    shutil.copyfile(checksums, evidence / "SHA256SUMS")
    for spec in lock["licenses"]:
        url = f"https://raw.githubusercontent.com/{lock['repository']}/{spec['ref']}/{spec['path']}"
        download(url, evidence / spec["name"], spec["sha256"], 128 * 1024)
    archive = download(base + lock["asset"]["name"], downloads / lock["asset"]["name"],
                       lock["asset"]["sha256"], lock["asset"]["size"])
    if archive.stat().st_size != lock["asset"]["size"]:
        raise ValueError("runtime archive size mismatch")
    write(evidence / "provenance.json", {
        "status": "publisher-input-identities-verified", "lock": lock,
        "archiveSha256": sha256(archive), "sourceBinaryCorrespondence": "not-established",
        "signaturePolicy": "relocatable upstream ad-hoc signatures; no Developer ID or notarization claim",
        "holds": ["v2.0 predates WineForge attribution correction 0072",
                  "dependency/input closure is not a verified reproducible build",
                  "no third-party runtime archive is republished by this workflow"]})
    return archive



def extract_runtime(archive, destination, directory, evidence=None):
    with tarfile.open(archive, "r:xz") as source:
        members = source.getmembers()
        if len(members) > 100000 or sum(item.size for item in members) > 8 * 1024**3:
            raise ValueError("runtime extraction exceeds quota")
        names = {item.name.rstrip("/") for item in members}
        selected, metadata = [], []
        for item in members:
            parts = Path(item.name).parts
            if not parts or ".." in parts or item.name.startswith("/"):
                raise ValueError("runtime archive member outside pinned root")
            # BSD tar stores xattrs in AppleDouble sidecars, including one beside
            # the top-level directory. Do not restore host provenance/quarantine
            # xattrs. Recognize bounded metadata by its actual format and a
            # corresponding contained payload member, never just its filename.
            counterpart = Path(item.name).with_name(Path(item.name).name[2:]).as_posix() if Path(item.name).name.startswith("._") else None
            if counterpart and item.isfile() and item.size <= 65536 and counterpart in names:
                data = source.extractfile(item).read()
                if data[:8] == bytes.fromhex("0005160700020000") and Path(counterpart).parts[0] == directory:
                    metadata.append({"path": item.name, "size": item.size,
                                     "sha256": hashlib.sha256(data).hexdigest()})
                    continue
            if parts[0] != directory:
                raise ValueError("runtime archive member outside pinned root: " + item.name)
            if not (item.isfile() or item.isdir() or item.issym() or item.islnk()) or item.mode & 0o6000:
                raise ValueError("runtime archive contains special or set-ID member")
            selected.append(item)
        if evidence:
            write(evidence / "archive-metadata.json", {"omittedAppleDouble": metadata,
                  "policy": "retain metadata hashes; do not restore publisher filesystem xattrs"})
        source.extractall(destination, members=selected, filter="data")
    return destination / directory



def command(args, log, *, env=None, timeout=120, check=True):
    with Path(log).open("wb") as output:
        result = subprocess.run(list(map(str, args)), env=env, stdout=output, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}); see {log}")
    return result



def audit_macho(runtime, evidence):
    records = []
    # Audit the core host runtime, not optional game payloads shipped elsewhere.
    roots = [runtime / "bin", runtime / "lib/wine/aarch64-unix", runtime / "libexec"]
    candidates = set(runtime.glob("lib/*.dylib"))
    for root in roots:
        candidates.update(root.rglob("*"))
    for path in sorted(candidates):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe"):
            continue
        architecture = subprocess.check_output(["lipo", "-archs", str(path)], text=True).strip()
        if architecture != "arm64":
            raise ValueError("core host runtime is not ARM64: " + str(path))
        signature = subprocess.run(["codesign", "--verify", "--strict", str(path)], capture_output=True, text=True)
        if signature.returncode:
            raise ValueError("invalid upstream Mach-O signature: " + str(path) + "\n" + signature.stderr)
        imports = subprocess.check_output(["otool", "-L", str(path)], text=True)
        for line in imports.splitlines()[1:]:
            dependency = line.strip().split(" (", 1)[0]
            if not dependency.startswith(("/usr/lib/", "/System/", "@rpath/", "@loader_path/", "@executable_path/")):
                raise ValueError("nonrelocatable host dependency: " + dependency)
        records.append({"path": str(path.relative_to(runtime)), "architecture": architecture,
                        "sha256": sha256(path), "signatureVerified": True, "imports": imports})
    if not any(item["path"] == "bin/wine-launcher" for item in records):
        raise ValueError("pinned native Wine launcher missing")
    write(evidence / "macho-audit.json", records)
