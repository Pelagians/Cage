"""Native CLI launch adapter using Cage's existing prefix lifecycle machinery."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from artifact.inspection import verify_bundle
from artifact.macos import verify_seal
from runtime.desktop_launch import (DesktopError, lifecycle_lock, plan_identity, prepare_generation,
                                    windows_path, document_arguments, assert_quiescent, state_info)
from runtime.macos import require_host, verify_runtime, store_path, execution_environment, command, write


def run_plan(bundle, *, store=None, state_dir=None, files=(), allow_host_access=False):
    bundle = Path(bundle).resolve()
    if not allow_host_access:
        raise DesktopError("native macOS launch requires --allow-host-access; it has ordinary user host access")
    verified = verify_bundle(bundle)
    if not verified.get("valid") or not verified.get("runnable"):
        raise DesktopError("native launch requires a verified runnable bundle: " + "; ".join(verified["errors"]))
    target = json.loads((bundle / "metadata/execution-target.json").read_text())
    receipt = json.loads((bundle / "metadata/desktop-build.json").read_text())
    plan = verify_seal(bundle, target, receipt)
    base = Path(state_dir).absolute() if state_dir else Path.home() / "Library/Application Support/Cage/macos"
    return {"schemaVersion": "cage.macos-run-plan/v0", "bundle": str(bundle), "contract": plan,
            "runtimeStore": str(store_path(store)), "stateRoot": str(base / plan["desktop"]["id"]),
            "files": list(map(str, files)), "fileArguments": document_arguments(files),
            "identity": plan_identity(plan)}


def execute(plan, *, timeout=None, state_action=None):
    require_host()
    if state_action not in {None, "state-info"}:
        raise DesktopError("native macOS updates/migrations are not qualified; state retained")
    root, bundle = Path(plan["stateRoot"]), Path(plan["bundle"])
    if state_action == "state-info":
        return {"success": True, "state": state_info(root, plan["identity"])}
    runtime = verify_runtime(plan["runtimeStore"])
    contract = plan["contract"]
    server, wine = runtime / contract["target"]["wineserver"], runtime / contract["target"]["wine"]
    with lifecycle_lock(root) as lock_fd:
        home = root / "home"
        env = execution_environment(runtime, root / "prefix", home)
        assert_quiescent(root, server, env)
        inventory = json.loads((bundle / "metadata/desktop-build.json").read_text())["inventory"]
        prefix, pending = prepare_generation(bundle / "prefix", inventory, root, plan["identity"], contract, None)
        if pending is not None:
            raise DesktopError("unexpected native state transition; all state retained")
        (home / "tmp").mkdir(parents=True, exist_ok=True)
        env = execution_environment(runtime, prefix, home)
        env.update(contract["environment"])
        z = prefix / "dosdevices/z:"
        if not z.exists(): z.symlink_to("/")
        launch = contract["launch"]
        executable = windows_path(prefix, launch["entrypoint"])
        cwd = windows_path(prefix, launch["workingDirectory"]) if launch.get("workingDirectory") else executable.parent
        args = [str(wine), launch["entrypoint"], *launch.get("args", []), *plan["fileArguments"]]
        result = {"schemaVersion": "cage.macos-run-result/v0", "success": False, "forcedCleanup": False}
        try:
            with (root / "application.log").open("wb") as log:
                process = subprocess.run(args, env=env, cwd=cwd, pass_fds=(lock_fd,),
                                         stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
            command([server, "-w"], root / "server-shutdown.log", env=env, timeout=60)
            result.update(success=process.returncode == 0, exitCode=process.returncode,
                          naturalServerShutdown=True, stateRoot=str(root), identity=plan["identity"])
            return result
        finally:
            # Never make shutdown green by killing services. An orphan refuses
            # the next launch through assert_quiescent; all state is retained.
            write(root / "last-run.json", result)
