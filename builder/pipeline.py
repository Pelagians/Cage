"""Compile and render one ordered build operation list."""
from __future__ import annotations

import shlex
from core.sources import container_source_path
from typing import Any

from core.compatibility import compatibility_environment
from core.manifest import Manifest
from core.modules import collect_build_steps
from core.build_step import BuildStep
from core.modules.base import ModuleError
from core.modules.paths import validate_linux_outputs


PREFIX_SEED_KIND = "prefix-seed"


def _shell_quote(value: str) -> str:
    """Quote a value for shell."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _launch_lines(manifest: Manifest) -> list[str]:
    """Generate launch configuration (entrypoints, file associations)."""
    launch = manifest.launch
    if not launch:
        return []

    lines = ['echo "[cage] Configuring launch"']
    if launch.entrypoint:
        entrypoint = _shell_quote(launch.entrypoint)
        lines.append(f'printf "  Entrypoint: %s\\n" {entrypoint}')
        lines.append(f'printf "%s\\n" {entrypoint} > "$WINEPREFIX/entrypoint"')
    if launch.args:
        quoted_args = " ".join(_shell_quote(arg) for arg in launch.args)
        lines.append(f'printf "  Args:"; printf " %s" {quoted_args}; printf "\\n"')
    if launch.env:
        for key, value in launch.env.items():
            lines.append(f"export {key}={_shell_quote(value)}")
    return lines


def _windows_prefix_relative_path(value: str) -> str:
    """Return a safe prefix-relative path for a C: launch target."""
    normalized = value.replace("\\", "/")
    if len(normalized) < 3 or normalized[1:3] != ":/" or normalized[0].lower() != "c":
        raise ValueError(f"launch entrypoint must be an absolute C: path: {value}")
    parts = [part for part in normalized[3:].split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"launch entrypoint contains an unsafe path: {value}")
    return "/".join(["drive_c", *parts])


def _export_lines(manifest: Manifest, *, bundle_mount: str) -> list[str]:
    """Verify and recoverably promote the completed Wine prefix."""
    entrypoint = manifest.launch.entrypoint if manifest.launch else None
    launch_relative = _windows_prefix_relative_path(entrypoint) if entrypoint else None
    requires_chocolatey = any(module.type == "chocolatey" for module in manifest.modules)
    lines = [
        'echo "[cage] Exporting bundle"',
        'test -d "$WINEPREFIX/drive_c" || { echo "[cage] ERROR: built Wine prefix is missing drive_c" >&2; exit 70; }',
        '# Z: is an ephemeral host mapping needed while Wine executes. Never copy it',
        '# into a portable bundle: z: -> / would recursively traverse the build host.',
        'rm -f "$WINEPREFIX/dosdevices/z:"',
        'rm -rf "$CAGE_PREFIX_PARTIAL"',
        'mkdir -p "$CAGE_PREFIX_PARTIAL"',
        'cp -a "$WINEPREFIX/." "$CAGE_PREFIX_PARTIAL/"',
        'CAGE_PREFIX_FILE_COUNT="$(find "$CAGE_PREFIX_PARTIAL" -type f -print | wc -l)"',
        'CAGE_PREFIX_BYTE_SIZE="$(du -sb "$CAGE_PREFIX_PARTIAL" | cut -f1)"',
        'test "$CAGE_PREFIX_FILE_COUNT" -gt 1 || { echo "[cage] ERROR: materialized prefix contains only a placeholder/baseline" >&2; exit 71; }',
        'test "$CAGE_PREFIX_BYTE_SIZE" -gt 0 || { echo "[cage] ERROR: materialized prefix is empty" >&2; exit 71; }',
    ]
    if requires_chocolatey:
        lines.extend([
            'echo "[cage] Verifying manifest-declared Chocolatey executable"',
            'case "${CFW_CHOCOLATEY_PREFIX_PATH:-}" in "$WINEPREFIX"/*) ;; *) echo "[cage] ERROR: CFW Chocolatey interface is outside the prepared prefix" >&2; exit 72 ;; esac',
            'CAGE_CHOCOLATEY_PREFIX_RELATIVE="${CFW_CHOCOLATEY_PREFIX_PATH#"$WINEPREFIX"/}"',
            'test -f "$CAGE_PREFIX_PARTIAL/$CAGE_CHOCOLATEY_PREFIX_RELATIVE" || { echo "[cage] ERROR: manifest-declared Chocolatey executable is missing" >&2; exit 72; }',
        ])
    if launch_relative:
        lines.extend([
            f'CAGE_LAUNCH_RELATIVE={_shell_quote(launch_relative)}',
            'echo "[cage] Verifying launch executable"',
            'test -f "$CAGE_PREFIX_PARTIAL/$CAGE_LAUNCH_RELATIVE" || { echo "[cage] ERROR: declared launch executable is missing" >&2; exit 73; }',
        ])
    lines.extend([
        'export CAGE_PREFIX_FILE_COUNT CAGE_PREFIX_BYTE_SIZE CAGE_PREFIX_METADATA_PARTIAL',
        "python3 -c 'import json, os; from pathlib import Path; Path(os.environ[\"CAGE_PREFIX_METADATA_PARTIAL\"]).write_text(json.dumps({\"schemaVersion\": \"cage.prefix-materialization/v0\", \"completed\": True, \"fileCount\": int(os.environ[\"CAGE_PREFIX_FILE_COUNT\"]), \"byteSize\": int(os.environ[\"CAGE_PREFIX_BYTE_SIZE\"])}, indent=2, sort_keys=True) + \"\\n\", encoding=\"utf-8\")'",
        'rm -rf "$CAGE_PREFIX_PREVIOUS"',
        'if [ -e "$CAGE_PREFIX_FINAL" ]; then mv "$CAGE_PREFIX_FINAL" "$CAGE_PREFIX_PREVIOUS"; fi',
        'if ! mv "$CAGE_PREFIX_PARTIAL" "$CAGE_PREFIX_FINAL"; then',
        '  if [ -e "$CAGE_PREFIX_PREVIOUS" ]; then mv "$CAGE_PREFIX_PREVIOUS" "$CAGE_PREFIX_FINAL"; fi',
        '  exit 74',
        'fi',
        'mv "$CAGE_PREFIX_METADATA_PARTIAL" "$CAGE_PREFIX_METADATA_FINAL"',
        'rm -rf "$CAGE_PREFIX_PREVIOUS"',
        'echo "  Bundle export complete"',
    ])
    return lines


def build_plan(manifest: Manifest) -> list[dict[str, object]]:
    """Compile the ordered operations executed by the build script.

    The CFW foundation is selected before execution, independently of where
    Chocolatey package actions appear in the recipe. All application steps
    retain their recipe position.
    """
    steps: list[dict[str, object]] = []
    root_build = any(module.type in {"script", "extract"} for module in manifest.modules)

    def append(op_id: str, phase: str, step: BuildStep, *, module_index: int | None = None,
               module_type: str | None = None, step_index: int | None = None,
               inputs: list[str] | None = None, resources: list[str] | None = None) -> None:
        payload = step.to_dict()
        payload.update({"id": op_id, "phase": phase, "inputs": inputs or [],
                        "resourceDependencies": resources or []})
        payload["executionUser"] = (
            "root" if root_build and (op_id == "prepare-build" or step.kind in {"linux-state", "linux-seal"}
                                      or module_type in {"script", "extract"}) else "application"
        )
        if step.kind == "media-mount":
            payload["resourcesCreated"] = [step.metadata["resource"]]
        if module_index is not None:
            payload.update({"moduleIndex": module_index, "moduleType": module_type,
                            "stepIndex": step_index})
            payload["metadata"] = {**payload.get("metadata", {}), "runtimeIdentity": {
                "provider": manifest.runtime.provider, "version": manifest.runtime.version,
                "runner": manifest.runtime.runner,
            }}
        steps.append(payload)

    init_commands = [
        'export WINEPREFIX="${CAGE_BUILD_PREFIX:-/tmp/cage-build-prefix}"',
        'export WINEDBG="-all"',
        'unset WINEDLLOVERRIDES',
        'CAGE_PREFIX_FINAL=' + _shell_quote('/opt/cage/prefix'),
        'CAGE_PREFIX_PARTIAL=' + _shell_quote('/opt/cage/prefix.partial'),
        'CAGE_PREFIX_PREVIOUS=' + _shell_quote('/opt/cage/prefix.previous'),
        'CAGE_PREFIX_METADATA_PARTIAL=' + _shell_quote('/opt/cage/metadata/prefix-materialization.partial.json'),
        'CAGE_PREFIX_METADATA_FINAL=' + _shell_quote('/opt/cage/metadata/prefix-materialization.json'),
        'export CAGE_PREFIX_FINAL CAGE_PREFIX_PARTIAL CAGE_PREFIX_PREVIOUS CAGE_PREFIX_METADATA_PARTIAL CAGE_PREFIX_METADATA_FINAL',
        'rm -rf "$WINEPREFIX" "$CAGE_PREFIX_PARTIAL" "$CAGE_PREFIX_PREVIOUS" "$CAGE_PREFIX_METADATA_PARTIAL"',
        'mkdir -p "$WINEPREFIX"',
        'rm -f /opt/cage/build/cfw-interface.env /opt/cage/logs/failed-operation',
    ]
    if root_build:
        init_commands.append('chown abc:abc "$WINEPREFIX"')
    if manifest.runtime.runner is not None:
        init_commands.extend([
            'export CAGE_RUNNER_BIN="${CAGE_RUNNER_BIN:-/opt/cage-runner/bin}"',
            'export PATH="$CAGE_RUNNER_BIN:$PATH"',
            'export WINE="$CAGE_RUNNER_BIN/wine"',
        ])
    # Global DLL policy belongs to launch, not build. WINEARCH alone must
    # precede prefix creation; other compatibility settings are launch-only.
    preinit_env = ({"WINEARCH": manifest.compatibility["arch"]}
                   if manifest.compatibility.get("arch") else {})
    init_commands.extend(f'export {key}={_shell_quote(value)}' for key, value in preinit_env.items())
    append("prepare-build", "prepare-build", BuildStep(init_commands, "Prepare build and prefix environment", kind="lifecycle"))

    chocolatey = next((m for m in manifest.modules if m.type == "chocolatey"), None)
    foundation_steps = chocolatey.foundation_steps() if chocolatey is not None else []
    seed_steps = [step for step in foundation_steps if step.kind in {"metadata", PREFIX_SEED_KIND}]
    readiness_steps = [step for step in foundation_steps if step.kind not in {"metadata", PREFIX_SEED_KIND}]
    for i, step in enumerate(seed_steps, 1):
        append(f"foundation-{i}", "prefix-seed", step)

    if chocolatey is not None:
        append("init-prefix", "init-prefix", BuildStep([
            'test -d "$WINEPREFIX/drive_c" || { echo "[cage] ERROR: prepared prefix is missing drive_c" >&2; exit 69; }',
            'cfw_interface_file="${CAGE_BUNDLE_MOUNT:-/opt/cage}/build/cfw-interface.env"',
            'test -f "$cfw_interface_file" || { echo "[cage] ERROR: CFW interface was not materialized" >&2; exit 68; }',
            'source "$cfw_interface_file"',
            'rm -f "$cfw_interface_file"',
            'touch "$WINEPREFIX/.cage-prefix-seeded"',
        ], "Adopt verified CFW prefix once", kind="prefix-adopt"))
    else:
        append("init-prefix", "init-prefix", BuildStep([
            'wineboot_log="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/wineboot.log"',
            'mkdir -p "$(dirname "$wineboot_log")"',
            'WINEDLLOVERRIDES=mscoree,mshtml= timeout 300s wineboot --init > "$wineboot_log" 2>&1 || { rc=$?; cat "$wineboot_log" >&2; exit "$rc"; }',
        ], "Initialize Wine prefix once", kind="wineboot", timeout=315))

    for i, step in enumerate(readiness_steps, 1):
        append(f"foundation-check-{i}", "foundation-check", step)
    if manifest.compatibility.get("windowsVersion"):
        version = manifest.compatibility["windowsVersion"]
        append("compatibility", "compatibility", BuildStep(
            [f"winecfg -v {_shell_quote(version)}"], "Set Windows version before modules", kind="wine-config"))

    active_media: dict[str, tuple[str, str]] = {}
    occupied_drives: set[str] = set()
    persistent_paths: list[str] = []
    for module_index, module, build_steps in collect_build_steps(manifest.modules):
        if module.type == "iso":
            if module.action == "mount":
                drive = module.drive.upper()
                if module.id in active_media or drive in occupied_drives:
                    raise ModuleError(f"modules[{module_index}] duplicates media ID or drive")
                active_media[module.id] = (drive, module.mount_path)
                occupied_drives.add(drive)
            else:
                mounted = active_media.pop(module.id, None)
                if mounted is None:
                    raise ModuleError(f"modules[{module_index}] unmounts unknown media: {module.id}")
                drive = mounted[0]
                occupied_drives.remove(drive)
                build_steps = [BuildStep([
                    f"wine reg delete 'HKLM\\Software\\Wine\\Drives' /v '{drive}:' /f",
                    f'rm -f -- "$WINEPREFIX/dosdevices/{drive.lower()}:"',
                ], f"Release ISO media: {module.id}", kind="media-unmount",
                    metadata={"resource": module.id, "drive": drive})]
        if module.type == "install" and module.source and len(module.source) > 2 and module.source[1:3] == ":/" and module.source[0].upper() != "C":
            requested = module.source[0].upper()
            if requested not in occupied_drives:
                raise ModuleError(f"modules[{module_index}] installer requires an active media drive {requested}:")
        if module.type == "script":
            persistent_paths.extend(module.outputs or [])
        if module.type == "dll" and module.install and module.install["target"] == "syswow64" and manifest.compatibility.get("arch") == "win32":
            raise ModuleError(f"modules[{module_index}] syswow64 requires a 64-bit Wine prefix")
        if module.type == "extract" and module.target and not module.target.startswith("/work/"):
            persistent_paths.append(module.target)
        for step_index, step in enumerate(build_steps, 1):
            if module.type == "install" and step.metadata.get("media"):
                source = module.source.replace("\\", "/")
                relative = source[3:]
                if not relative or any(part in {"", ".", ".."} for part in relative.split("/")):
                    raise ModuleError(f"modules[{module_index}] installer escapes its media root")
                media_root = next(root for drive, root in active_media.values()
                                  if drive == source[0].upper())
                mounted_root = container_source_path(media_root)
                media_file = mounted_root + "/" + relative
                commands = list(step.commands)
                # A previous operation must not replace the Wine drive link
                # between the ISO declaration and this installer.
                commands.insert(0, f'test "$(readlink -- "$WINEPREFIX/dosdevices/{source[0].lower()}:")" = {_shell_quote(mounted_root)}')
                if module.sha256:
                    file_arg = _shell_quote(media_file)
                    commands[1:1] = [
                        f'test -f {file_arg}',
                        f'test "$(realpath -e -- {file_arg})" = {file_arg}',
                        f'test "$(sha256sum -- {file_arg} | cut -d " " -f1)" = {_shell_quote(module.sha256.lower())}',
                    ]
                step = BuildStep(commands, step.description, kind=step.kind,
                    environment=step.environment, working_dir=step.working_dir,
                    timeout=step.timeout, unsafe=step.unsafe,
                    metadata={**step.metadata, "mediaPath": media_file if module.sha256 else None})
            if module.type == "chocolatey":
                step = BuildStep(step.commands, step.description, kind=step.kind,
                    environment={**step.environment,
                                 "CAGE_CHOCOLATEY_EVIDENCE_NAME": f"chocolatey-package-evidence-{module_index + 1}.json"},
                    working_dir=step.working_dir, timeout=step.timeout, unsafe=step.unsafe,
                    metadata={**step.metadata,
                              "packageEvidence": f"metadata/chocolatey-package-evidence-{module_index + 1}.json"})
            inputs = ([module.source] if getattr(module, "source", None) else [])
            inputs += ([module.file] if getattr(module, "file", None) and module.type in {"script", "registry"} else [])
            if module.type == "files":
                inputs.extend(mapping["source"] for mapping in module.mappings or [])
            if module.type == "dll" and module.install:
                inputs.append(module.install["source"])
            resources = ([resource for resource, (drive, _) in active_media.items()
                          if module.type == "install" and module.source
                          and module.source.upper().startswith(drive + ":/")])
            if module.type == "iso" and module.action == "unmount":
                resources = [module.id]
            append(f"module-{module_index + 1}-step-{step_index}",
                   f"module-{module_index + 1}-step-{step_index}", step,
                   module_index=module_index + 1, module_type=module.type, step_index=step_index,
                   inputs=inputs, resources=resources)

    for resource, (drive, _) in active_media.items():
        append(f"release-media-{resource}", "release-media", BuildStep([
            f"wine reg delete 'HKLM\\Software\\Wine\\Drives' /v '{drive}:' /f",
            f'rm -f -- "$WINEPREFIX/dosdevices/{drive.lower()}:"',
        ], f"Release outstanding build media: {resource}", kind="media-cleanup",
            metadata={"resource": resource, "drive": drive}))
    for index, path in enumerate(validate_linux_outputs(persistent_paths), 1):
        destination = '/opt/cage/linux-root' + path
        append(f"capture-linux-{index}", "capture-linux", BuildStep([
            f'test "$(realpath -e -- {_shell_quote(path)})" = {_shell_quote(path)}',
            f'mkdir -p -- "$(dirname -- {_shell_quote(destination)})"',
            f'cp -a -- {_shell_quote(path)} {_shell_quote(destination)}',
        ], f"Capture Linux artifact state: {path}", kind="linux-state",
            metadata={"path": path, "imageBase": "qualified-runtime"}))
    if persistent_paths:
        entries = " ".join(_shell_quote(path.lstrip("/")) for path in persistent_paths)
        append("seal-linux-state", "seal-linux-state", BuildStep([
            'test -z "$(find /opt/cage/linux-root \\( -type l -o \\( ! -type f -a ! -type d \\) \\) -print -quit)"',
            f"tar --sort=name --mtime=@0 --numeric-owner --format=posix --pax-option=delete=atime,delete=ctime -C /opt/cage/linux-root -cf /opt/cage/linux-state.tar -- {entries}",
            'chmod 0644 /opt/cage/linux-state.tar',
            'rm -rf /opt/cage/linux-root',
        ], "Seal declared Linux filesystem state", kind="linux-seal"))

    append("launch", "launch", BuildStep(_launch_lines(manifest), "Configure launch", kind="launch"))
    append("export", "export", BuildStep(_export_lines(manifest, bundle_mount="/opt/cage"),
                                         "Export built prefix", kind="seal"))
    return steps


def generate_build_script(
    manifest: Manifest,
    *,
    bundle_mount: str = "/opt/cage",
    workspace_mount: str = "/workspace",
) -> str:
    """Render the same compiled operations recorded in the bundle plan."""
    if bundle_mount != "/opt/cage" or workspace_mount != "/workspace":
        raise ValueError("custom build mounts are unsupported by the compiled v0 plan")
    root_build = any(module.type in {"script", "extract"} for module in manifest.modules)
    lines = ["#!/bin/bash", "set -euo pipefail", "",
             'CAGE_OPERATION_ID=prepare-build',
             'trap \'rc=$?; rm -rf "${CAGE_PREFIX_PARTIAL:-/opt/cage/prefix.partial}" "${CAGE_PREFIX_METADATA_PARTIAL:-/opt/cage/metadata/prefix-materialization.partial.json}"; if [ "$rc" -ne 0 ]; then printf "%s %s\\n" "$CAGE_OPERATION_ID" "$rc" > /opt/cage/logs/failed-operation; fi\' EXIT',
             'echo "[cage] Starting build"']
    for operation in build_plan(manifest):
        lines.extend([
            "",
            f'CAGE_OPERATION_ID={_shell_quote(str(operation["id"]))}',
            f'printf "[cage] Operation %s: %s\\n" {_shell_quote(str(operation["id"]))} {_shell_quote(str(operation["description"]))}',
        ])
        step = BuildStep(
            commands=list(operation["commands"]),
            description=str(operation["description"]),
            kind=str(operation["kind"]),
            environment=dict(operation.get("environment") or {}),
            working_dir=operation.get("workingDir"),
            timeout=operation.get("timeout"),
            unsafe=bool(operation.get("unsafe", False)),
            metadata=dict(operation.get("metadata") or {}),
        )
        body = step.to_shell_lines()
        if root_build and operation["executionUser"] == "application":
            lines.append("s6-setuidgid abc bash -c " + shlex.quote("set -euo pipefail\n" + "\n".join(body)))
        else:
            lines.extend(body)
    lines.append('echo "[cage] Build complete"')
    return "\n".join(lines) + "\n"


__all__ = ["PREFIX_SEED_KIND", "generate_build_script", "build_plan"]
