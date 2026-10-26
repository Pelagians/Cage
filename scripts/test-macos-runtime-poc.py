#!/usr/bin/env python3
"""Standalone Darwin runtime experiment; deliberately not a Cage runtime adapter.

Only a new disposable work directory is touched. Failure cleanup is recorded and
can never turn a failed shutdown into a pass. Publisher identity/input checks
do not claim a reproducible build or authenticate source-to-binary equivalence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.manifest import load_manifest
from core.media import stage_media
from runtime.desktop_launch import inventory_tree

LOCK = ROOT / "tests/fixtures/macos-metalsharp-v2.0.json"
ORIGINAL = b"Original macOS document\n"
FIRST = b"Cage macOS saved through Notepad++\n"
SECOND = FIRST + b"Relaunch verified\n"


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


def extract_runtime(archive, destination, directory):
    with tarfile.open(archive, "r:xz") as source:
        members = source.getmembers()
        if len(members) > 100000 or sum(item.size for item in members) > 8 * 1024**3:
            raise ValueError("runtime extraction exceeds quota")
        for item in members:
            parts = Path(item.name).parts
            if not parts or parts[0] != directory or ".." in parts or item.name.startswith("/"):
                raise ValueError("runtime archive member outside pinned root")
            if not (item.isfile() or item.isdir() or item.issym() or item.islnk()) or item.mode & 0o6000:
                raise ValueError("runtime archive contains special or set-ID member")
        source.extractall(destination, filter="data")
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


def wait_for(predicate, description, process=None, seconds=90):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{description}: driver exited {process.returncode}")
        time.sleep(0.1)
    raise TimeoutError(description)


def windows(path):
    value = str(Path(path).absolute())
    if any(c in value for c in '\r\n"'):
        raise ValueError("unsupported test path")
    return "Z:" + value.replace("/", "\\")


def runtime_processes(runtime):
    listing = subprocess.check_output(["ps", "-axo", "pid=,ppid=,command="], text=True)
    return listing, [line for line in listing.splitlines() if str(runtime) in line]


def functional(lock, runtime, work, evidence, probe):
    environment = {key: value for key, value in os.environ.items()
                   if key in {"USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}}
    prefix = work / "prefix"
    for name in ("home", "tmp"):
        (work / name).mkdir()
    environment.update(lock["environment"], WINEPREFIX=str(prefix), HOME=str(work / "home"),
                       TMPDIR=str(work / "tmp"), PATH=str(runtime / "bin") + ":/usr/bin:/bin:/usr/sbin:/sbin")
    wine, server = runtime / "bin/wine", runtime / "bin/wineserver"
    write(evidence / "execution-environment.json", {key: environment[key] for key in
          [*lock["environment"], "WINEPREFIX", "HOME", "TMPDIR", "PATH"]})
    command([wine, "--version"], evidence / "wine-version.txt", env=environment)
    if "wine-11.20" not in (evidence / "wine-version.txt").read_text():
        raise ValueError("unexpected Wine version")
    processes = []
    try:
        command([wine, "wineboot", "--init"], evidence / "wineboot.log", env=environment, timeout=180)
        command([server, "-w"], evidence / "wineboot-shutdown.log", env=environment, timeout=90)
        manifest = load_manifest(ROOT / lock["applicationRecipe"])
        source = manifest.sources[0]
        if source.sha256 != lock["applicationSha256"] or manifest.version != "8.8.8":
            raise ValueError("application recipe differs from pinned Asahi input")
        archive = download(source.url, work / "downloads" / "notepad.zip", source.sha256, 128 * 1024**2)
        staged = stage_media(archive, name="notepad-seed", workspace=work)
        seed = Path(staged["stagedPath"])
        seed_inventory = inventory_tree(seed)
        write(evidence / "application-seed-inventory.json", seed_inventory)
        app = prefix / "drive_c/cage-proof/Notepad++"
        shutil.copytree(seed, app)
        # Match the existing recipe's exclusion without changing the seed.
        if (app / "updater").exists():
            shutil.rmtree(app / "updater")
        document = work / "Proof café with spaces.txt"
        document.write_bytes(ORIGINAL)
        prefix_identity = prefix.stat().st_ino
        rounds = []
        for number, expected in ((1, FIRST), (2, SECOND)):
            result = evidence / f"round-{number}.json"
            ready = result.with_name(result.name + ".ready")
            close = result.with_name(result.name + ".close")
            with (evidence / f"round-{number}.log").open("wb") as log:
                process = subprocess.Popen([str(wine), str(probe), str(number), windows(app / "notepad++.exe"),
                                            windows(document), windows(result)], env=environment,
                                           cwd=app, stdout=log, stderr=subprocess.STDOUT)
                processes.append(process)
                wait_for(ready.is_file, "visible editor / saved receipt", process)
                receipt = json.loads(ready.read_text())
                if not receipt["visibleEditor"] or min(receipt["windowWidth"], receipt["windowHeight"]) <= 0:
                    raise ValueError("visible application window not established")
                wait_for(lambda: document.read_bytes() == expected, "exact document save", process, seconds=30)
                shutil.copyfile(document, evidence / f"saved-{number}.txt")
                # Supplementary desktop evidence; GUI assertions use Win32, not a TCC bypass.
                capture = command(["screencapture", "-x", evidence / f"round-{number}.png"],
                                  evidence / f"screenshot-{number}.log", check=False)
                receipt["screenshotExitCode"] = capture.returncode
                write(evidence / f"observed-{number}.json", receipt)
                close.touch()
                if process.wait(timeout=60) != 0:
                    raise RuntimeError("GUI driver/application did not close successfully")
            closed = json.loads(result.read_text())
            if closed["phase"] != "closed" or closed["applicationExitCode"] != 0:
                raise ValueError("application clean exit not established")
            command([server, "-w"], evidence / f"server-wait-{number}.log", env=environment, timeout=60)
            listing, remaining = runtime_processes(runtime)
            (evidence / f"processes-after-{number}.txt").write_text(listing)
            if remaining:
                raise RuntimeError("native runtime processes remain after natural shutdown: " + str(remaining))
            if prefix.stat().st_ino != prefix_identity:
                raise ValueError("prefix was replaced between launches")
            configs = list(app.glob("config.xml")) + list(prefix.glob("drive_c/users/*/AppData/Roaming/Notepad++/config.xml"))
            zooms = [ET.parse(path).find(".//GUIConfig[@name='ScintillaPrimaryView']") for path in configs]
            if not any(node is not None and node.get("zoom") == "3" for node in zooms):
                raise ValueError("application zoom preference was not persisted")
            for index, path in enumerate(configs):
                shutil.copyfile(path, evidence / f"settings-{number}-{index}.xml")
            rounds.append(closed)
        if inventory_tree(seed) != seed_inventory:
            raise ValueError("application source seed changed")
        return {"rounds": rounds, "samePrefix": True, "saveRelaunch": True,
                "settingsPersisted": True, "cleanShutdown": True, "forcedCleanup": False,
                "immutableApplicationSeed": True, "documentSha256": sha256(document)}
    except BaseException:
        # This is failure cleanup only. The caller retains a failed result.
        write(evidence / "failure-cleanup.json", {"forcedCleanup": True, "scope": str(prefix)})
        for process in processes:
            if process.poll() is None:
                process.terminate()
        command([server, "-k"], evidence / "failure-server-kill.log", env=environment, timeout=20, check=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--probe-sha256", required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    result = {"schemaVersion": "cage.macos-runtime-proof/v0", "status": "failed",
              "scope": "native runtime experiment; not a Cage target or sandbox qualification"}
    try:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise ValueError("proof requires a native Apple Silicon macOS runner")
        args.work = args.work.absolute()
        args.work.mkdir()  # Refuse reuse, including a pre-existing symlink.
        (args.work / "downloads").mkdir()
        lock = json.loads(LOCK.read_text())
        if sha256(args.probe) != args.probe_sha256:
            raise ValueError("GUI probe artifact checksum mismatch")
        with args.probe.open("rb") as stream:
            header = stream.read(64)
            if header[:2] != b"MZ":
                raise ValueError("GUI probe is not PE")
            stream.seek(int.from_bytes(header[60:64], "little"))
            if stream.read(6) != b"PE\0\0\x64\x86":
                raise ValueError("GUI probe is not Windows x64")
        command(["sw_vers"], args.evidence / "macos-version.txt")
        result.update(hostArchitecture=platform.machine(), hostPageSize=os.sysconf("SC_PAGE_SIZE"),
                      runnerImage=os.environ.get("ImageVersion"), workflowCommit=os.environ.get("GITHUB_SHA"),
                      probeSha256=args.probe_sha256, lockSha256=sha256(LOCK))
        archive = provenance(lock, args.work / "downloads", args.evidence)
        runtime = extract_runtime(archive, args.work, lock["runtimeDirectory"])
        runtime_inventory = inventory_tree(runtime)
        write(args.evidence / "runtime-inventory.json", runtime_inventory)
        if not (runtime / "share/licenses/wine/LICENSE").is_file() or not (runtime / "share/licenses/fex/LICENSE").is_file():
            raise ValueError("runtime component notices missing")
        audit_macho(runtime, args.evidence)
        result.update(functional(lock, runtime, args.work, args.evidence, args.probe.absolute()))
        if inventory_tree(runtime) != runtime_inventory:
            raise ValueError("upstream runtime bytes or metadata changed during execution")
        result.update(status="passed", immutableRuntime=True,
                      provenance="publisher-input-identities-verified; source-to-binary correspondence not established")
    except BaseException as exc:
        result.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        raise
    finally:
        write(args.evidence / "result.json", result)
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
