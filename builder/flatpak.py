"""Flatpak target adapter for the existing ordered Cage build pipeline."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import signal
import hashlib
import shutil
import tempfile

from artifact.bundle import create_bundle, update_bundle_execution_metadata
from artifact.desktop import seal_desktop_bundle, validate_desktop_recipe
from artifact.inspection import verify_bundle
from builder.pipeline import generate_build_script
from core.sources import verify_manifest_sources, audit_manifest_sources
from runtime.desktop_launch import DesktopError
from runtime.desktop_launch import inventory_tree, verify_inventory
from core.media import stage_media


def snapshot_sources(manifest, workspace, destination):
    """Bind copied module inputs to the recipe's pinned files/archives."""
    workspace, destination = Path(workspace).resolve(), Path(destination)
    inputs = []
    for module in manifest.modules:
        if module.type == "files":
            inputs.extend((m["source"], m.get("sha256")) for m in module.mappings)
        elif module.type == "registry" and module.file:
            inputs.append((module.file, module.sha256))
    for name, declared_hash in inputs:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise DesktopError("desktop inputs must be relative workspace paths")
        source, copied = workspace / relative, destination / relative
        if copied.exists():
            continue
        if source.is_symlink():
            raise DesktopError("desktop source cannot be a symlink")
        copied.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            pins = [s.sha256 for s in manifest.sources if s.path == name and s.sha256]
            expected = declared_hash or (pins[0] if pins else None)
            if not expected:
                raise DesktopError(f"desktop file source needs a checksum: {name}")
            shutil.copyfile(source, copied)
            if hashlib.sha256(copied.read_bytes()).hexdigest() != expected:
                raise DesktopError(f"copied desktop source hash mismatch: {name}")
        elif source.is_dir():
            receipt_path = source.parent / "metadata/media-stage.json"
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise DesktopError(f"directory input needs Cage media staging from a pinned archive: {name}")
            receipt = json.loads(receipt_path.read_text())
            matches = [s for s in manifest.sources if s.sha256 == receipt.get("sourceSha256") and s.path]
            if len(matches) != 1:
                raise DesktopError(f"staged directory has no unique pinned archive: {name}")
            archive = workspace / matches[0].path
            if archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != matches[0].sha256:
                raise DesktopError("staged archive hash mismatch")
            with tempfile.TemporaryDirectory() as td:
                expected = stage_media(archive, name="verified", workspace=Path(td))
                inventory = inventory_tree(Path(expected["stagedPath"]))
                shutil.copytree(source, copied, symlinks=True)
                verify_inventory(copied, inventory)
        else:
            raise DesktopError(f"missing desktop source: {name}")
    return destination


def run_flatpak(arguments, *, store, timeout=1200):
    print("[cage desktop] flatpak " + arguments[0], file=sys.stderr, flush=True)
    environment = {**os.environ, "FLATPAK_USER_DIR": str(Path(store).resolve())}
    try:
        process = subprocess.Popen(["flatpak", *arguments], env=environment, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate(timeout=15)
            raise DesktopError(f"flatpak {arguments[0]} timed out after {timeout}s:\n{output[-12000:]}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DesktopError(f"Flatpak command failed: {exc}") from exc
    if process.returncode:
        raise DesktopError(f"flatpak {arguments[0]} failed ({process.returncode}):\n{output[-12000:]}")
    return output.strip()


def ensure_target(target, store):
    if platform.system().lower() != target["os"]:
        raise DesktopError(f"desktop target requires {target['os']}; this host is {platform.system()}")
    if platform.machine() != target["architecture"]:
        raise DesktopError(f"desktop target requires {target['architecture']}; this host is {platform.machine()}; use an appropriate build runner")
    run_flatpak(["remote-add", "--user", "--if-not-exists", target["remote"], target["remoteUrl"]], store=store)
    commits = {}
    references = [
        ("runtime", target["platform"], target["branch"], target["platformCommit"]),
        ("runtime", target["sdk"], target["branch"], target["sdkCommit"]),
    ]
    if target.get("base"):
        references.append(("app", target["base"], target["baseBranch"], target["baseCommit"]))
    for kind, name, branch, commit in references:
        ref = f"{kind}/{name}/{target['architecture']}/{branch}"
        try:
            installed = run_flatpak(["info", "--user", "--show-commit", ref], store=store)
        except DesktopError:
            run_flatpak(["install", "--user", "--noninteractive", "--assumeyes", "--no-related", target["remote"], ref], store=store)
            installed = run_flatpak(["info", "--user", "--show-commit", ref], store=store)
        if installed != commit:
            run_flatpak(["update", "--user", "--noninteractive", "--assumeyes", "--no-related", f"--commit={commit}", ref], store=store)
        actual = run_flatpak(["info", "--user", "--show-commit", ref], store=store)
        if actual != commit:
            raise DesktopError(f"runtime identity mismatch for {ref}")
        commits[ref] = actual
    if target.get("base"):
        actual_runtime = run_flatpak(["info", "--user", "--show-runtime", target["base"]], store=store)
        if actual_runtime != f"{target['platform']}/{target['architecture']}/{target['branch']}":
            raise DesktopError("Wine base uses a different Freedesktop platform")
    else:
        from runtime.arm64ec import materialize_payload
        materialize_payload(Path(store) / "arm64ec")
    return commits


def initialize_flatpak(build_dir, app_id, target, store):
    base = [f"--base={target['base']}", f"--base-version={target['baseBranch']}"] if target.get("base") else []
    run_flatpak(["build-init", f"--arch={target['architecture']}", *base, str(build_dir), app_id,
                 target["sdk"], target["platform"], target["branch"]], store=store)
    if target.get("payload") == "rpm":
        from runtime.arm64ec import materialize_payload
        shutil.copytree(materialize_payload(Path(store) / "arm64ec"), Path(build_dir) / "files", symlinks=True, dirs_exist_ok=True)
    # New application policy: never inherit the Wine base application's permissions.
    (Path(build_dir) / "metadata").write_text(
        f"[Application]\nname={app_id}\nruntime={target['platform']}/{target['architecture']}/{target['branch']}\n"
        f"sdk={target['sdk']}/{target['architecture']}/{target['branch']}\n")
    for directory in ("share/applications", "share/metainfo", "share/appdata"):
        path = Path(build_dir) / "files" / directory
        if path.exists():
            shutil.rmtree(path)


def build_flatpak_bundle(manifest, output, *, workspace, store, timeout=900):
    target = validate_desktop_recipe(manifest)
    integrity = verify_manifest_sources(manifest, workspace=workspace)
    policy = audit_manifest_sources(manifest, workspace=workspace)
    if not integrity["valid"] or not policy["valid"]:
        raise DesktopError("source preflight failed: " + "; ".join([*integrity["errors"], *policy["errors"]]))
    if not manifest.sources or any(not source.sha256 for source in manifest.sources):
        raise DesktopError("desktop builds require checksum-pinned source declarations")
    commits = ensure_target(target, store)
    bundle = create_bundle(manifest, Path(output), dry_run=False)
    # A build marker is written before execution so container paths fail closed,
    # including after failed/partial desktop builds.
    (bundle / "metadata/execution-target.json").write_text(json.dumps(target, indent=2) + "\n")
    build_dir = bundle / "build/flatpak"
    try:
        inputs = snapshot_sources(manifest, workspace, bundle / "build/inputs")
        initialize_flatpak(build_dir, manifest.desktop["id"], target, store)
    except (DesktopError, OSError, ValueError) as exc:
        update_bundle_execution_metadata(bundle, state="build-failed", runnable=False,
                                         has_default_launch=True, error=str(exc), log_excerpt=str(exc))
        raise
    for name, payload in (("source-integrity", integrity), ("source-policy", policy)):
        (bundle / f"metadata/{name}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    script = generate_build_script(manifest, settle_prefix=True)
    (bundle / "build/run.sh").write_text(script)
    # Same operations, same /opt/cage and /workspace contract; only execution adapts.
    args = ["build", "--die-with-parent", "--unshare=network", "--share=ipc", "--socket=x11", "--env=WINEARCH=win64",
            "--env=WINEPREFIX=/tmp/cage-build-prefix",
            "--env=WINEDEBUG=-all", f"--bind-mount=/opt/cage={bundle}",
            f"--bind-mount=/workspace={inputs}", str(build_dir)]
    try:
        version = run_flatpak([*args, "/app/bin/wine", "--version"], store=store)
        if version != target["wineVersionOutput"]:
            raise DesktopError(f"Wine version mismatch: {version}")
        wrapper = "trap 'wineserver -k || true' EXIT; bash /opt/cage/build/run.sh"
        log = run_flatpak([*args, "bash", "-c", wrapper], store=store, timeout=timeout)
        (bundle / "logs/build.log").write_text(log + "\n")
        # Confirm the base identity did not change while build-init copied its files.
        if target.get("base") and run_flatpak(["info", "--user", "--show-commit", target["base"]], store=store) != target["baseCommit"]:
            raise DesktopError("Wine base changed during build")
        seal_desktop_bundle(bundle, target, {"wineVersion": version, "commits": commits})
        update_bundle_execution_metadata(bundle, state="runnable", runnable=True, materialized_prefix=True,
                                         has_default_launch=True, exit_code=0, log_excerpt=log[-4000:])
        provenance = json.loads((bundle / "metadata/provenance.json").read_text())
        provenance.update(builder="cage-flatpak-target", executionTarget=target,
                          recipeRuntime=provenance.get("runtime"),
                          runtime=json.loads((bundle / "runtime/runtime.json").read_text()),
                          notes=["Built by the existing ordered pipeline under the pinned desktop target; OCI binding describes recipe intent only."])
        (bundle / "metadata/provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
        if not verify_bundle(bundle)["valid"]:
            raise DesktopError("desktop build failed existing bundle verification")
    except (DesktopError, OSError, ValueError) as exc:
        (bundle / "logs/build.log").write_text(str(exc) + "\n")
        update_bundle_execution_metadata(bundle, state="build-failed", runnable=False,
                                         has_default_launch=True, error=str(exc), log_excerpt=str(exc))
        raise
    return {"schemaVersion": "cage.desktop-build-result/v0", "success": True, "bundle": str(bundle), "target": target}
