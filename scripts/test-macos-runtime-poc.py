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

from runtime.macos import (LOCK, write, sha256, download, api, verify_metadata, provenance,
                           extract_runtime, command, audit_macho)
ORIGINAL = b"Original macOS document\n"
FIRST = b"Cage macOS saved through Notepad++\n"
SECOND = FIRST + b"Relaunch verified\n"


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
        listing, _ = runtime_processes(runtime)
        (evidence / "processes-at-failure.txt").write_text(listing)
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
        print("Verifying publisher release, source identities and downloaded bytes", flush=True)
        archive = provenance(lock, args.work / "downloads", args.evidence)
        print("Extracting contained payload and checking native code signatures", flush=True)
        runtime = extract_runtime(archive, args.work, lock["runtimeDirectory"], args.evidence)
        runtime_inventory = inventory_tree(runtime)
        write(args.evidence / "runtime-inventory.json", runtime_inventory)
        if not (runtime / "share/licenses/wine/LICENSE").is_file() or not (runtime / "share/licenses/fex/LICENSE").is_file():
            raise ValueError("runtime component notices missing")
        audit_macho(runtime, args.evidence)
        print("Starting native Wine and the two-round GUI/shutdown proof", flush=True)
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
