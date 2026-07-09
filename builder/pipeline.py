"""Simplified build script generator for module-first architecture.

This builder generates shell scripts by calling module.build() methods
in declaration order, with each module logging its execution.
"""
from __future__ import annotations

from typing import Any

from core.compatibility import compatibility_environment
from core.manifest import Manifest
from core.modules import generate_module_script


def _shell_quote(value: str) -> str:
    """Quote a value for shell."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _runner_environment_lines(manifest: Manifest) -> list[str]:
    """Generate environment variable setup for the runner."""
    runner = manifest.runtime.runner
    if not runner:
        return []
    
    lines = [
        'echo "[cage] Configuring runner environment"',
    ]
    
    # Add runner-specific environment variables
    if isinstance(runner, dict):
        for key, value in runner.items():
            lines.append(f"export {key}={_shell_quote(str(value))}")
    
    return lines


def _compatibility_policy_lines(manifest: Manifest) -> list[str]:
    """Generate compatibility policy setup (DLL overrides, Windows version, etc.)."""
    compat = manifest.compatibility
    if not compat:
        return []
    
    lines = [
        'echo "[cage] Applying compatibility policy"',
    ]
    
    for key, value in compatibility_environment(compat).items():
        lines.append(f"export {key}={_shell_quote(value)}")
        if key == "WINEDLLOVERRIDES" and value:
            lines.append(f'echo "  DLL overrides: {value}"')
    
    # Windows version
    windows_version = compat.get("windowsVersion")
    if windows_version:
        lines.append(f'echo "  Setting Windows version: {windows_version}"')
        lines.append(f"winecfg -v {windows_version}")
    
    # Graphics backend
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
    
    lines = [
        'echo "[cage] Configuring launch"',
    ]
    
    # Entrypoint
    if launch.entrypoint:
        lines.append(f'echo "  Entrypoint: {launch.entrypoint}"')
        # Write entrypoint configuration
        lines.append(f'echo "{launch.entrypoint}" > $WINEPREFIX/entrypoint')
    
    # Args
    if launch.args:
        args_str = " ".join(launch.args)
        lines.append(f'echo "  Args: {args_str}"')
    
    # Environment
    if launch.env:
        for key, value in launch.env.items():
            lines.append(f"export {key}={_shell_quote(value)}")
    
    return lines


def _export_lines(manifest: Manifest) -> list[str]:
    """Generate export/bundle packaging commands."""
    lines = [
        'echo "[cage] Exporting bundle"',
        # Create rootfs directory in bundle mount
        'mkdir -p /opt/cage/rootfs',
        # Copy Wine prefix to rootfs
        'WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"',
        'if [ -d "$WINEPREFIX" ]; then',
        '  echo "  Copying Wine prefix to rootfs..."',
        '  cp -a "$WINEPREFIX/." /opt/cage/rootfs/',
        '  echo "  Wine prefix copied successfully"',
        'else',
        '  echo "  WARNING: Wine prefix not found at $WINEPREFIX"',
        'fi',
        'echo "  Bundle export complete"',
    ]
    return lines


def build_plan(manifest: Manifest) -> list[dict[str, object]]:
    """Generate a build plan (list of steps) for the manifest.
    
    This is for backward compatibility with tests and other code that expects
    a list of build steps rather than a shell script.
    
    Args:
        manifest: The manifest to build
    
    Returns:
        List of step dicts with 'phase', 'description', and 'commands' keys
    """
    steps = []
    
    # Phase 1: Init prefix
    steps.append({
        "id": "init-prefix",
        "phase": "init-prefix",
        "kind": "wineboot",
        "description": "Initialize Wine prefix",
        "commands": ["wine wineboot --init"],
        "unsafe": False,
    })
    
    # Phase 2: Execute modules
    total_modules = len(manifest.modules)
    for i, module in enumerate(manifest.modules, 1):
        build_steps = module.build()
        for step_index, step in enumerate(build_steps, 1):
            step_payload = step.to_dict()
            step_payload.update({
                "id": f"module-{i}-step-{step_index}",
                "phase": f"module-{i}-step-{step_index}",
                "description": f"Module {i}/{total_modules} ({module.type}): {step.description}",
                "moduleType": module.type,
                "moduleIndex": i,
                "stepIndex": step_index,
            })
            steps.append(step_payload)
    
    # Phase 3: Configure launch
    if manifest.launch:
        steps.append({
            "id": "launch",
            "phase": "launch",
            "kind": "raw-shell",
            "description": "Configure launch",
            "commands": ["echo 'Configuring launch'"],
            "unsafe": False,
        })
    
    # Phase 4: Export bundle
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
    """Generate a bash build script for the manifest.
    
    The script executes modules in declaration order, with each module
    logging "Running Module X/Y (Type)" before executing.
    
    Args:
        manifest: The manifest to build
        bundle_mount: Mount point for the bundle output
        workspace_mount: Mount point for the workspace
        timeout_per_phase: Timeout per phase in seconds
    
    Returns:
        Shell script as a string
    """
    lines = [
        '#!/bin/bash',
        'set -euo pipefail',
        '',
        '# Suppress Wine debugger',
        'export WINEDBG="-all"',
        '',
        f'echo "[cage] Starting build for {manifest.name} v{manifest.version}"',
        f'echo "[cage] Bundle mount: {bundle_mount}"',
        f'echo "[cage] Workspace mount: {workspace_mount}"',
        'echo ""',
        "",
        # Phase 1: Initialize Wine prefix
        'echo "[cage] Phase 1: Initializing Wine prefix"',
        'timeout 300s wine wineboot --init 2>&1 | while IFS= read -r line; do echo "  $line"; done',
        'echo "[cage]   Prefix initialized"',
        'echo ""',
        '',
    ]
    
    # Add runner environment setup if runner is specified
    if manifest.runtime.runner is not None:
        lines.extend([
            'echo "[cage] Configuring runner environment"',
            'export CAGE_RUNNER_BIN="${CAGE_RUNNER_BIN:-/opt/cage-runner/bin}"',
            'export PATH="$CAGE_RUNNER_BIN:$PATH"',
            'export WINE="$CAGE_RUNNER_BIN/wine"',
            'echo "  Using cached Wine runner at $CAGE_RUNNER_BIN"',
            'echo ""',
            '',
        ])
    
    lines.extend([
        'echo "[cage] Phase 2: Executing modules"',
        *_runner_environment_lines(manifest),
        "",
        # Compatibility policy
        *_compatibility_policy_lines(manifest),
        'echo ""',
        "",
        # Phase 2: Execute modules in declaration order
        'echo "[cage] Phase 2: Executing modules"',
        generate_module_script(manifest.modules),
        'echo ""',
        "",
        # Phase 3: Configure launch
        'echo "[cage] Phase 3: Configuring launch"',
        *_launch_lines(manifest),
        'echo ""',
        "",
        # Phase 4: Export bundle
        'echo "[cage] Phase 4: Exporting bundle"',
        *_export_lines(manifest),
        'echo ""',
        "",
        'echo "[cage] Build complete"',
    ])
    
    return "\n".join(lines)


__all__ = ["generate_build_script"]
