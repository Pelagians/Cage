"""Explicit native macOS recipe and immutable launch contract. No app packaging."""
from __future__ import annotations

import json
from pathlib import Path
import re

from core.compatibility import compatibility_environment
from core.manifest import Manifest
from runtime.desktop_launch import DesktopError, digest_json, windows_path
from runtime.macos import runtime_target


def validate_recipe(manifest):
    target = runtime_target()
    if (manifest.schema_version != "cage.app/v0" or manifest.runtime.provider != target["provider"]
            or manifest.runtime.version != target["version"] or not manifest.desktop or not manifest.launch):
        raise DesktopError("macOS target requires a v0 recipe with the pinned wine-macos runtime, desktop identity and launch")
    if (manifest.runtime.network != "host" or manifest.build.network != "host"
            or manifest.runtime.wine_graphics != "winemac"):
        raise DesktopError("native macOS requires explicit host access for build/run and winemac graphics; network isolation is not implemented")
    if any((manifest.runtime.image, manifest.runtime.runner, manifest.runtime.digest,
            manifest.runtime.channel, manifest.runtime.source, manifest.exports)):
        raise DesktopError("macOS runtime overrides and additional exports are unqualified")
    for entry in manifest.entrypoints:
        if (len(manifest.entrypoints) != 1 or entry['executable'] != manifest.launch.entrypoint
                or entry.get('args', []) != manifest.launch.args or entry.get('env', {}) != manifest.launch.env
                or entry.get('workingDirectory') != manifest.launch.working_directory):
            raise DesktopError("native macOS initially supports the default entrypoint only")
    for module in manifest.modules:
        if module.type not in {"files", "registry", "check"} or (module.type == "check" and module.command):
            raise DesktopError("native macOS supports files, registry and file checks only; CFW/installers/scripts remain unqualified")
        if module.type == "registry" and (module.user != "application" or module.view != "default"):
            raise DesktopError("native registry builds initially support the default view/application user")
    policy = manifest.compatibility
    if policy.get("arch", "win64") != "win64" or policy.get("graphics"):
        raise DesktopError("macOS initially qualifies win64 prefixes with its default winemac profile; graphics overrides are unqualified")
    if policy.get("dllPolicy"):
        raise DesktopError("custom DLL policy is not qualified by the initial macOS target")
    for name in {**policy.get("env", {}), **manifest.launch.env}:
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                or name in {"PATH", "HOME", "TMPDIR", "USER", "LOGNAME", "GRAPHICS_BACKEND", "OPENGL_BACKEND"}
                or name.startswith(("WINE", "FEX_", "LD_", "DYLD_", "CAGE_", "GST_", "VK_", "ROSETTA_", "XDG_"))):
            raise DesktopError("native launch environment key is runtime-owned or invalid: " + name)
    return target


def read_manifest(bundle):
    data = json.loads((Path(bundle) / "manifest.cage.json").read_text())
    if "compatibility" in data:
        data["compatibility"] = {key: value for key, value in data["compatibility"].items() if key != "schemaVersion"}
    return Manifest.from_dict(data)


def launch_plan(manifest, seed_digest):
    target = validate_recipe(manifest)
    return {"schemaVersion": "cage.macos-launch/v0", "format": "macos", "target": target,
            "application": {"name": manifest.name, "version": manifest.version}, "desktop": manifest.desktop,
            "launch": manifest.launch.to_dict(), "seedDigest": seed_digest,
            "environment": {**compatibility_environment(manifest.compatibility), **manifest.launch.env},
            "state": {"managerVersion": 1}, "hostAccess": "ordinary-user; no sandbox/network isolation"}


def verify_seal(bundle, target, receipt):
    if target != runtime_target():
        raise DesktopError("unknown macOS runtime; retain the exact runtime used to build this bundle")
    manifest = read_manifest(bundle)
    expected = launch_plan(manifest, receipt["seedDigest"])
    path = Path(bundle) / "metadata/macos-launch.json"
    if path.is_symlink() or json.loads(path.read_text()) != expected:
        raise DesktopError("native macOS launch seal differs from its recipe/runtime/seed")
    if receipt.get("runtimeEvidence", {}).get("payloadDigest") != target["payloadDigest"]:
        raise DesktopError("native macOS runtime closure receipt mismatch")
    executable = windows_path(Path(bundle) / "prefix", manifest.launch.entrypoint)
    with executable.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise DesktopError("macOS entrypoint is not Windows PE")
        stream.seek(int.from_bytes(header[60:64], "little"))
        if stream.read(6) != b"PE\0\0\x64\x86":
            raise DesktopError("macOS target initially qualifies Windows x64 entrypoints only")
    return expected
