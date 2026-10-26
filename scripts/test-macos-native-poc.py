#!/usr/bin/env python3
"""Prove Cage's native CLI build/run, immutable seed and persistent prefix."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact.inspection import verify_bundle
from core.manifest import load_manifest
from core.media import stage_media
from runtime.macos import runtime_target, verify_runtime, execution_environment, download, command, sha256, write
from runtime.desktop_launch import inventory_tree

spec = importlib.util.spec_from_file_location("macos_gui", ROOT / "scripts/test-macos-runtime-poc.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--probe-sha256", required=True)
    args = parser.parse_args()
    evidence = args.evidence.absolute(); evidence.mkdir(parents=True, exist_ok=True)
    work = args.work.absolute()
    result = {"schemaVersion": "cage.macos-native-functional-test/v0", "status": "failed", "forcedCleanup": False}
    processes, bundle, helper_env, runtime = [], None, None, None
    packaged, package_inventory = None, None
    document, number = None, None
    try:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("native Apple Silicon macOS required")
        work.mkdir()
        if sha256(args.probe) != args.probe_sha256:
            raise RuntimeError("Windows test helper artifact changed")
        recipe = ROOT / "recipes/notepadplusplus-portable-macos.cage.yaml"
        manifest = load_manifest(recipe)
        source = manifest.sources[0]
        archive = work / source.path; archive.parent.mkdir(parents=True)
        download(source.url, archive, source.sha256, 128 * 1024**2)
        stage_media(archive, name="notepadplusplus-portable", workspace=work)
        cli = [sys.executable, "-m", "cage"]
        store, state = work / "runtime", work / "state"
        build = [*cli, "build", recipe, "--target", "macos", "--workspace", work, "--output", work / "bundles",
                 "--macos-store", store, "--allow-host-access"]
        command([*build, "--dry-run"], evidence / "build-plan.json")
        if store.exists() or state.exists() or (work / "bundles").exists():
            raise RuntimeError("native planning created runtime, state or bundle files")
        bundle = work / "bundles" / (manifest.name + "-" + manifest.version)
        command(build, evidence / "build.log", timeout=1200)
        verification = verify_bundle(bundle)
        write(evidence / "bundle-verification.json", verification)
        if not verification["valid"] or not verification["runnable"]:
            raise RuntimeError("native CLI build did not produce a runnable verified bundle")
        operations = json.loads((bundle / "metadata/native-operations.json").read_text())
        if [op["kind"] for op in operations if op["moduleIndex"]] != ["copy-tree", "registry", "check"]:
            raise RuntimeError("native build lost declaration order")
        # Build paths must not be required to consume a sealed bundle.
        relocated = work / "relocated native bundle"
        shutil.move(bundle, relocated); bundle = relocated
        command([*cli, "bundle", "verify", bundle], evidence / "relocated-verification.json")
        runtime = verify_runtime(store)
        target = runtime_target()
        root = state / manifest.desktop["id"]
        document = work / "Proof café with spaces.txt"; document.write_bytes(gui.ORIGINAL)
        seed = inventory_tree(bundle / "prefix")
        run = [*cli, "run", bundle, document, "--macos-store", store, "--state-dir", state,
               "--allow-host-access", "--timeout", "180"]
        command([*run, "--dry-run"], evidence / "run-plan.json")
        if root.exists():
            raise RuntimeError("native run planning created mutable state")
        identity = None
        rounds = []
        packaged_first = gui.SECOND + b"Packaged launch verified\n"
        packaged_second = packaged_first + b"Packaged relaunch verified\n"
        for number, expected in ((1, gui.FIRST), (2, gui.SECOND), (3, packaged_first), (4, packaged_second)):
            if number == 3:
                output = work / "Notepad Cage.app"
                export = [*cli, "export", "macos-app", bundle, "--output", output,
                          "--macos-store", store, "--state-dir", state, "--tool-cache", work / "app-tools", "--allow-host-access"]
                command([*export, "--dry-run"], evidence / "app-export-plan.json")
                if output.exists(): raise RuntimeError("app export planning created a package")
                command(export, evidence / "app-export.json", timeout=600)
                receipt = json.loads((evidence / "app-export.json").read_text())
                if receipt["plan"]["config"]["identity"] != json.loads(identity)["generations"][0]["identity"]:
                    raise RuntimeError("packaging changed the CLI state identity")
                packaged = work / "Applications with spaces" / "Notepad café.app"
                packaged.parent.mkdir(); shutil.move(output, packaged)
                package_inventory = inventory_tree(packaged)
                command([packaged / "Contents/MacOS/CageLauncher", "--cage-verify"], evidence / "app-relocated-signature.log")
            if number == 4:
                moved = work / "Moved again" / "Notepad café.app"
                moved.parent.mkdir(); shutil.move(packaged, moved); packaged = moved
            launch = run if number <= 2 else ["/usr/bin/open", "-n", "-W", "-a", packaged, document]
            report = evidence / f"round-{number}.json"
            ready, close = Path(str(report) + ".ready"), Path(str(report) + ".close")
            application_log = root / "application.log"
            previous_log = application_log.stat().st_mtime_ns if application_log.exists() else None
            previous_result = (root / "last-run.json").stat().st_mtime_ns if (root / "last-run.json").exists() else None
            with (evidence / f"cage-run-{number}.json").open("wb") as out, (evidence / f"cage-run-{number}.log").open("wb") as err:
                app = subprocess.Popen(list(map(str, launch)), cwd=work, stdout=out, stderr=err)
                processes.append(app)
                gui.wait_for((root / "state.json").is_file, "Cage persistent state initialization", app, seconds=90)
                # Retained state already exists on relaunch. Starting the Wine
                # driver at that point races Cage's quiescence check. Cage opens
                # this log only after that check and generation preparation.
                gui.wait_for(lambda: application_log.exists() and application_log.stat().st_mtime_ns != previous_log,
                             "Cage application launch after quiescence check", app, seconds=90)
                record = json.loads((root / "state.json").read_text())
                prefix = root / record.get("active", "prefix")
                helper_env = execution_environment(runtime, prefix, root / "home")
                with (evidence / f"gui-driver-{number}.log").open("wb") as log:
                    driver = subprocess.Popen([str(runtime / "bin/wine"), str(args.probe.absolute()), "--attach", str(number),
                                               gui.windows(document), gui.windows(report)], env=helper_env, stdout=log, stderr=subprocess.STDOUT)
                    processes.append(driver)
                    gui.wait_for(ready.is_file, "Cage-launched visible Notepad++ editor and save", driver)
                    gui.wait_for(lambda: document.read_bytes() == expected, "exact saved host bytes", driver, seconds=30)
                    shutil.copyfile(document, evidence / f"saved-{number}.txt")
                    command(["screencapture", "-x", evidence / f"round-{number}.png"], evidence / f"screenshot-{number}.log", check=False)
                    close.touch()
                    if driver.wait(timeout=45) != 0:
                        raise RuntimeError("GUI driver rejected native application/registry persistence")
                if app.wait(timeout=90) != 0:
                    raise RuntimeError("cage run failed its application or natural server shutdown gate")
            closed = json.loads(report.read_text())
            if (root / "last-run.json").stat().st_mtime_ns == previous_result:
                raise RuntimeError("application returned without a new Cage lifecycle receipt")
            run_result = json.loads((root / "last-run.json").read_text())
            if (closed["applicationExitCode"] != 0 or not closed["registrySeedVerified"] or closed["launchCounter"] != number
                    or not run_result["success"] or not run_result["naturalServerShutdown"] or run_result["forcedCleanup"]):
                raise RuntimeError("native close/state receipts do not establish success")
            listing, remaining = gui.runtime_processes(runtime)
            (evidence / f"processes-after-{number}.txt").write_text(listing)
            if remaining:
                raise RuntimeError("native processes remain after Cage returned")
            if packaged is not None and any(str(packaged) in line for line in listing.splitlines()):
                raise RuntimeError("packaged launcher/Python remains after LaunchServices returned")
            if identity is None:
                identity = (root / "state.json").read_bytes()
            elif (root / "state.json").read_bytes() != identity:
                raise RuntimeError("native relaunch changed the state generation")
            rounds.append(closed)
            shutil.copyfile(root / "state.json", evidence / f"state-{number}.json")
            shutil.copyfile(root / "last-run.json", evidence / f"last-run-{number}.json")
            shutil.copyfile(application_log, evidence / f"application-{number}.log")
        if inventory_tree(bundle / "prefix") != seed:
            raise RuntimeError("launch changed the sealed source prefix")
        # Modified runtime files must fail before mutable state or Wine starts.
        canary = runtime / "README.md"; original = canary.read_bytes()
        try:
            canary.write_bytes(original + b"\nCage tamper test\n")
            denied = command(run, evidence / "modified-runtime-refusal.log", check=False)
            if denied.returncode == 0 or (root / "state.json").read_bytes() != identity:
                raise RuntimeError("modified runtime was accepted or changed state")
        finally:
            canary.write_bytes(original)
        verify_runtime(store)
        if inventory_tree(packaged) != package_inventory:
            raise RuntimeError("launch modified the application package")
        # The native host must reject changed resources before executing Python.
        config = packaged / "Contents/Resources/app-config.json"
        original_config = config.read_bytes()
        try:
            config.write_bytes(original_config + b"\n ")
            denied = command([packaged / "Contents/MacOS/CageLauncher", "--cage-verify"], evidence / "app-tamper-refusal.log", check=False)
            if denied.returncode == 0 or (root / "state.json").read_bytes() != identity:
                raise RuntimeError("changed app package accepted or altered state")
        finally:
            config.write_bytes(original_config)
        command([packaged / "Contents/MacOS/CageLauncher", "--cage-verify"], evidence / "app-final-signature.log")
        final_verification = verify_bundle(bundle)
        if not final_verification["valid"]:
            raise RuntimeError("sealed native bundle changed after launch")
        command(["sw_vers"], evidence / "macos-version.txt")
        result.update(status="passed", build=True, run=True, saveRelaunch=True, registryPersistence=True,
                      sameStateGeneration=True, immutableSeed=True, runtimeTamperRefused=True, cleanShutdown=True,
                      appPackaging=True, launchServices=True, appRelocation=True, immutableApp=True, appTamperRefused=True,
                      rounds=rounds, target=target["id"], runtimePayloadDigest=target["payloadDigest"],
                      hostPageSize=os.sysconf("SC_PAGE_SIZE"), runnerImage=os.environ.get("ImageVersion"),
                      testedCommit=os.environ.get("GITHUB_SHA"), scope="native CLI and local ad-hoc-signed .app; ordinary host access")
    except BaseException as exc:
        result.update(error=type(exc).__name__ + ": " + str(exc), failedRound=number, forcedCleanup=True)
        # Preserve the actual failed UI and document before disposable-runner
        # cleanup; never retry edits or substitute a successful receipt.
        if document is not None and document.is_file():
            shutil.copyfile(document, evidence / "failed-document.txt")
        try:
            command(["screencapture", "-x", evidence / "failure.png"], evidence / "failure-screenshot.log",
                    check=False, timeout=10)
        except Exception as capture_error:
            result["screenshotError"] = str(capture_error)
        for process in processes:
            if process.poll() is None: process.terminate()
        if runtime is not None and helper_env is not None:
            command([runtime / "bin/wineserver", "-k"], evidence / "failure-cleanup.log", env=helper_env, check=False, timeout=20)
        raise
    finally:
        if bundle is not None and bundle.exists():
            for directory in ("metadata", "logs"):
                shutil.copytree(bundle / directory, evidence / ("bundle-" + directory), dirs_exist_ok=True)
        if (work / "runtime/verification").is_dir():
            shutil.copytree(work / "runtime/verification", evidence / "runtime-verification", dirs_exist_ok=True)
        for state_root in (work / "state").glob("*"):
            for name in ("application.log", "server-shutdown.log", "last-run.json"):
                if (state_root / name).is_file():
                    shutil.copyfile(state_root / name, evidence / ("final-" + name))
        if (work / "Notepad Cage.app.build").exists():
            shutil.copytree(work / "Notepad Cage.app.build", evidence / "app-build", dirs_exist_ok=True)
        for log in (Path.home() / "Library/Logs/Cage").glob("*/app-launch.log"):
            shutil.copyfile(log, evidence / "app-launch.log")
        write(evidence / "result.json", result)
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
