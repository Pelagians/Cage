"""Build script generator for Cage's module-first architecture.

Most module steps execute in declaration order after Wine initialization.
``prefix-seed`` steps are the one pipeline-owned exception: they materialize a
producer-complete prefix foundation before application modules. Cage does not
rerun ``wineboot`` against that producer-owned compatibility state.
"""
from __future__ import annotations

from typing import Any

from core.compatibility import compatibility_environment
from core.manifest import Manifest
from core.modules import collect_build_steps, generate_module_script


PREFIX_SEED_KIND = "prefix-seed"


def _shell_quote(value: str) -> str:
    """Quote a value for shell."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _runner_environment_lines(manifest: Manifest) -> list[str]:
    """Generate environment variable setup for the runner."""
    runner = manifest.runtime.runner
    if not runner:
        return []

    lines = ['echo "[cage] Configuring runner environment"']
    if isinstance(runner, dict):
        for key, value in runner.items():
            lines.append(f"export {key}={_shell_quote(str(value))}")
    return lines


def _compatibility_policy_lines(manifest: Manifest) -> list[str]:
    """Generate compatibility policy setup (DLL overrides, Windows version, etc.)."""
    compat = manifest.compatibility
    if not compat:
        return []

    lines = ['echo "[cage] Applying compatibility policy"']
    for key, value in compatibility_environment(compat).items():
        lines.append(f"export {key}={_shell_quote(value)}")
        if key == "WINEDLLOVERRIDES" and value:
            lines.append(f'echo "  DLL overrides: {value}"')

    windows_version = compat.get("windowsVersion")
    if windows_version:
        lines.append(f'echo "  Setting Windows version: {windows_version}"')
        lines.append(f"winecfg -v {windows_version}")

    graphics = compat.get("graphics", {})
    backend = graphics.get("backend")
    if backend:
        lines.append(f'echo "  Graphics backend: {backend}"')
    return lines


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
        'trap - EXIT',
        'echo "  Bundle export complete"',
    ])
    return lines


def build_plan(manifest: Manifest) -> list[dict[str, object]]:
    """Generate a build plan with prepared-prefix steps before Wine init."""
    steps: list[dict[str, object]] = []
    collected = collect_build_steps(manifest.modules)

    for module_index, module, build_steps in collected:
        for step_index, step in enumerate(build_steps, 1):
            if step.kind != PREFIX_SEED_KIND:
                continue
            payload = step.to_dict()
            payload.update({
                "id": f"module-{module_index + 1}-seed-{step_index}",
                "phase": "prefix-seed",
                "description": f"Module {module_index + 1}/{len(manifest.modules)} ({module.type}): {step.description}",
                "moduleType": module.type,
                "moduleIndex": module_index + 1,
                "stepIndex": step_index,
            })
            steps.append(payload)

    steps.append({
        "id": "init-prefix",
        "phase": "init-prefix",
        "kind": "wineboot",
        "description": "Initialize or update Wine prefix",
        "commands": ["wine wineboot --init-or-update"],
        "unsafe": False,
    })

    for module_index, module, build_steps in collected:
        for step_index, step in enumerate(build_steps, 1):
            if step.kind == PREFIX_SEED_KIND:
                continue
            payload = step.to_dict()
            payload.update({
                "id": f"module-{module_index + 1}-step-{step_index}",
                "phase": f"module-{module_index + 1}-step-{step_index}",
                "description": f"Module {module_index + 1}/{len(manifest.modules)} ({module.type}): {step.description}",
                "moduleType": module.type,
                "moduleIndex": module_index + 1,
                "stepIndex": step_index,
            })
            steps.append(payload)

    if manifest.launch:
        steps.append({
            "id": "launch",
            "phase": "launch",
            "kind": "raw-shell",
            "description": "Configure launch",
            "commands": ["echo 'Configuring launch'"],
            "unsafe": False,
        })
    steps.append({
        "id": "export",
        "phase": "export",
        "kind": "copy-tree",
        "description": "Export bundle",
        "commands": ["echo 'Exporting bundle'"],
        "unsafe": False,
    })
    return steps


def generate_build_script(
    manifest: Manifest,
    *,
    bundle_mount: str = "/opt/cage",
    workspace_mount: str = "/workspace",
    timeout_per_phase: int = 300,
) -> str:
    """Generate the real build script."""
    seed_script = generate_module_script(
        manifest.modules,
        include_kinds={PREFIX_SEED_KIND},
        phase_label="prefix seed",
    )
    module_script = generate_module_script(
        manifest.modules,
        exclude_kinds={PREFIX_SEED_KIND},
    )
    if seed_script and manifest.runtime.runner is not None:
        raise ValueError(
            "CFW prepared runtimes cannot use runtime.runner; the producer image owns Wine identity"
        )

    lines = [
        '#!/bin/bash',
        'set -euo pipefail',
        '',
        'export WINEDBG="-all"',
        '',
        f'echo "[cage] Starting build for {manifest.name} v{manifest.version}"',
        f'echo "[cage] Bundle mount: {bundle_mount}"',
        f'echo "[cage] Workspace mount: {workspace_mount}"',
        'export WINEPREFIX="${CAGE_BUILD_PREFIX:-/tmp/cage-build-prefix}"',
        f'CAGE_PREFIX_FINAL={_shell_quote(bundle_mount + "/prefix")}',
        f'CAGE_PREFIX_PARTIAL={_shell_quote(bundle_mount + "/prefix.partial")}',
        f'CAGE_PREFIX_PREVIOUS={_shell_quote(bundle_mount + "/prefix.previous")}',
        f'CAGE_PREFIX_METADATA_PARTIAL={_shell_quote(bundle_mount + "/metadata/prefix-materialization.partial.json")}',
        f'CAGE_PREFIX_METADATA_FINAL={_shell_quote(bundle_mount + "/metadata/prefix-materialization.json")}',
        'export CAGE_PREFIX_FINAL CAGE_PREFIX_PARTIAL CAGE_PREFIX_PREVIOUS CAGE_PREFIX_METADATA_PARTIAL CAGE_PREFIX_METADATA_FINAL',
        'rm -rf "$WINEPREFIX" "$CAGE_PREFIX_PARTIAL" "$CAGE_PREFIX_PREVIOUS" "$CAGE_PREFIX_METADATA_PARTIAL"',
        'mkdir -p "$WINEPREFIX"',
        'trap \'rm -rf "$CAGE_PREFIX_PARTIAL" "$CAGE_PREFIX_METADATA_PARTIAL"\' EXIT',
        '',
    ]

    if manifest.runtime.runner is not None:
        lines.extend([
            'echo "[cage] Configuring runner environment"',
            'export CAGE_RUNNER_BIN="${CAGE_RUNNER_BIN:-/opt/cage-runner/bin}"',
            'export PATH="$CAGE_RUNNER_BIN:$PATH"',
            'export WINE="$CAGE_RUNNER_BIN/wine"',
            'echo "  Using cached Wine runner at $CAGE_RUNNER_BIN"',
            '',
        ])

    if seed_script:
        lines.extend([
            'echo "[cage] Phase 0: Seeding prepared prefix"',
            seed_script,
            'test -d "$WINEPREFIX/drive_c" || { echo "[cage] ERROR: prefix seed did not create drive_c" >&2; exit 68; }',
            'touch "$WINEPREFIX/.cage-prefix-seeded"',
            'echo "[cage]   Prepared prefix seeded"',
            '',
        ])

    if seed_script:
        lines.extend([
            'echo "[cage] Phase 1: Adopting prepared Wine prefix"',
            'test -d "$WINEPREFIX/drive_c" || { echo "[cage] ERROR: prepared Wine prefix is missing drive_c" >&2; exit 69; }',
            'echo "[cage]   Prepared prefix adopted; skipping producer-owned wineboot lifecycle"',
            '',
        ])
    else:
        lines.extend([
            'echo "[cage] Phase 1: Initializing Wine prefix"',
            'wineboot_log="${CAGE_BUNDLE_MOUNT:-/opt/cage}/logs/wineboot.log"',
            'mkdir -p "$(dirname "$wineboot_log")"',
            'set +e',
            'timeout 300s wine wineboot --init > "$wineboot_log" 2>&1',
            'wineboot_rc="$?"',
            'set -e',
            'sed "s/^/  /" "$wineboot_log" || true',
            'if [ "$wineboot_rc" -ne 0 ]; then',
            '  echo "[cage] ERROR: wineboot --init failed with exit code $wineboot_rc; see $wineboot_log" >&2',
            '  exit "$wineboot_rc"',
            'fi',
            'echo "[cage]   Prefix initialized"',
            '',
        ])

    lines.extend([
        'echo "[cage] Phase 2: Executing modules"',
        *_runner_environment_lines(manifest),
        '',
        *_compatibility_policy_lines(manifest),
        '',
        module_script,
        '',
        'echo "[cage] Phase 3: Configuring launch"',
        *_launch_lines(manifest),
        '',
        'echo "[cage] Phase 4: Exporting bundle"',
        *_export_lines(manifest, bundle_mount=bundle_mount),
        '',
        'echo "[cage] Build complete"',
    ])
    return "\n".join(lines)


__all__ = ["PREFIX_SEED_KIND", "generate_build_script", "build_plan"]
