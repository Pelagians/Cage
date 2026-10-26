"""Native adapter for Cage's ordered recipe operations; never executes Linux shell steps."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

from artifact.bundle import create_bundle, update_bundle_execution_metadata
from artifact.desktop import normalize_seed, seal_desktop_bundle
from artifact.macos import validate_recipe, launch_plan
from artifact.inspection import verify_bundle
from builder.flatpak import snapshot_sources
from builder.pipeline import build_plan
from core.modules.base import files_exclusions
from core.modules.registry import compile_reg
from core.sources import verify_manifest_sources, audit_manifest_sources
from runtime.desktop_launch import DesktopError, inventory_tree, windows_path
from runtime.macos import ensure_runtime, execution_environment, command, sha256, write


def input_path(root, value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not (Path(root) / path).resolve().is_relative_to(Path(root).resolve()):
        raise DesktopError("native input escapes the verified workspace")
    return Path(root) / path


def execute_module(operation, prefix, inputs, wine, env, build, log):
    metadata = operation["metadata"]
    kind = operation["kind"]
    if kind == "copy-tree":
        for mapping in metadata["mappings"]:
            source = input_path(inputs, mapping["source"])
            destination = windows_path(prefix, mapping["target"])
            if mapping.get("mode", "copy") == "copy" and destination.exists():
                if destination.is_dir(): shutil.rmtree(destination)
                else: destination.unlink()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
            for name in files_exclusions(mapping):
                excluded = destination / name
                if not excluded.resolve().is_relative_to(destination.resolve()):
                    raise DesktopError("native exclusion escapes its destination")
                if excluded.is_dir() and not excluded.is_symlink(): shutil.rmtree(excluded)
                else: excluded.unlink(missing_ok=True)
    elif kind == "registry":
        registry = input_path(inputs, metadata["source"]) if metadata.get("source") else build / (operation["id"] + ".reg")
        if not metadata.get("source"):
            registry.write_bytes(compile_reg(metadata["changes"]).encode("utf-16"))
        z = prefix / "dosdevices/z:"
        if not z.exists(): z.symlink_to("/")
        command([wine, "regedit", "/S", "Z:" + str(registry).replace("/", "\\")], log, env=env)
    elif kind == "check":
        spec = metadata["file"]
        path = windows_path(prefix, spec["path"]) if spec["path"].lower().startswith("c:/") else input_path(inputs, spec["path"])
        if path.exists() != spec.get("exists", True) or (spec.get("sha256") and sha256(path) != spec["sha256"]):
            raise DesktopError("native file check failed: " + spec["path"])
    else:
        raise DesktopError("unqualified native build operation: " + kind)


def build_macos_bundle(manifest, output, *, workspace, store=None, allow_host_access=False, timeout=300):
    target = validate_recipe(manifest)
    if not allow_host_access:
        raise DesktopError("native macOS builds require --allow-host-access (ordinary host access)")
    integrity = verify_manifest_sources(manifest, workspace=workspace)
    policy = audit_manifest_sources(manifest, workspace=workspace)
    if not integrity["valid"] or not policy["valid"] or not manifest.sources or any(not s.sha256 for s in manifest.sources):
        raise DesktopError("native build requires verified checksum-pinned source declarations")
    runtime = ensure_runtime(store)
    bundle = create_bundle(manifest, Path(output), dry_run=False)
    (bundle / "logs/build.log").write_text("[cage] Native macOS build started; no Linux shell steps are executed.\n")
    write(bundle / "metadata/execution-target.json", target)
    home, prefix = bundle / "build/home", bundle / "prefix"
    (home / "tmp").mkdir(parents=True)
    env = execution_environment(runtime, prefix, home)
    wine, server = runtime / target["wine"], runtime / target["wineserver"]
    observations = []
    try:
        inputs = snapshot_sources(manifest, workspace, bundle / "build/inputs")
        for name, value in (("source-integrity", integrity), ("source-policy", policy)):
            write(bundle / f"metadata/{name}.json", value)
        for operation in build_plan(manifest):
            kind, op_id = operation["kind"], operation["id"]
            print("[cage macOS build] " + op_id, file=sys.stderr, flush=True)
            log = bundle / "logs" / (op_id + ".log")
            if kind == "lifecycle":
                pass  # Prepared the native build/home/prefix paths above.
            elif kind == "wineboot":
                command([wine, "wineboot", "--init"], log, env=env, timeout=timeout)
                command([server, "-w"], bundle / "logs/init-server.log", env=env, timeout=60)
                normalize_seed(prefix)
            elif kind == "wine-config":
                command([wine, "winecfg", "-v", manifest.compatibility["windowsVersion"]], log, env=env, timeout=timeout)
            elif kind in {"copy-tree", "registry", "check"}:
                execute_module(operation, prefix, inputs, wine, env, bundle / "build", log)
            elif kind == "launch":
                if not windows_path(prefix, manifest.launch.entrypoint).is_file():
                    raise DesktopError("native build did not produce its declared application")
            elif kind == "seal":
                command([server, "-w"], bundle / "logs/build-server.log", env=env, timeout=60)
            else:
                raise DesktopError("unsupported native lifecycle operation: " + kind)
            observations.append({"id": op_id, "kind": kind, "moduleIndex": operation.get("moduleIndex"), "status": "passed"})
        receipt = seal_desktop_bundle(bundle, target, {"payloadDigest": target["payloadDigest"], "archiveSha256": target["asset"]["sha256"]})
        write(bundle / "metadata/macos-launch.json", launch_plan(manifest, receipt["seedDigest"]))
        files = [path for path in prefix.rglob("*") if path.is_file()]
        write(bundle / "metadata/prefix-materialization.json", {"schemaVersion": "cage.prefix-materialization/v0", "completed": True,
              "fileCount": len(files), "byteSize": sum(path.stat().st_size for path in files)})
        provenance = json.loads((bundle / "metadata/provenance.json").read_text())
        provenance.update(builder="cage-macos", runtime=target, executionTarget=target,
                          notes=["Ordered Cage operations executed by the native adapter; recorded Linux shell commands are not executed.",
                                 "Ordinary user host access; no sandbox or source-to-binary reproducibility claim."])
        write(bundle / "metadata/provenance.json", provenance)
        update_bundle_execution_metadata(bundle, state="runnable", runnable=True, materialized_prefix=True,
                                         has_default_launch=True, exit_code=0)
        verification = verify_bundle(bundle)
        if not verification["valid"]:
            raise DesktopError("native bundle verification failed: " + "; ".join(verification["errors"]))
        (bundle / "logs/build.log").write_text("[cage] Native build and immutable bundle verification passed.\n")
    except BaseException as exc:
        (bundle / "logs/build.log").write_text("[cage] Native build failed: " + str(exc) + "\n")
        update_bundle_execution_metadata(bundle, state="build-failed", runnable=False, error=str(exc))
        raise
    finally:
        write(bundle / "metadata/native-operations.json", observations)
    return {"success": True, "bundle": str(bundle), "target": target, "seedDigest": receipt["seedDigest"]}
