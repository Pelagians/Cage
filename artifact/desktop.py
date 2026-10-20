"""Shared, format-independent desktop payload and qualification boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from artifact.inspection import verify_bundle
from artifact.linux_state import declared_outputs
from core.compatibility import compatibility_environment
from core.manifest import Manifest
from runtime.desktop_launch import DesktopError, digest_json, inventory_tree, verify_inventory, windows_path


def desktop_target():
    return json.loads((Path(__file__).resolve().parents[1] / "runtime/desktop-wine-11.0.json").read_text())


def validate_desktop_recipe(manifest):
    target = desktop_target()
    if not manifest.desktop or not manifest.launch:
        raise DesktopError("desktop export requires desktop metadata and a default launch")
    if manifest.runtime.provider != target["provider"] or manifest.runtime.version != target["version"]:
        raise DesktopError("the desktop POC requires pinned Wine 11.0")
    if manifest.runtime.runner or manifest.runtime.image or manifest.runtime.digest:
        raise DesktopError("custom OCI images/runners cannot be substituted for a qualified desktop runtime")
    if manifest.runtime.wine_graphics != "xwayland" or manifest.runtime.network != "none" or manifest.build.network != "none":
        raise DesktopError("the desktop POC supports X11/XWayland and offline build/run only")
    if manifest.entrypoints or manifest.file_associations or manifest.exports:
        raise DesktopError("suite entrypoints, associations and additional outputs need later desktop qualification")
    for module in manifest.modules:
        if module.type not in {"files", "registry", "check"} or (module.type == "check" and module.command):
            raise DesktopError(f"desktop POC cannot qualify module {module.type}; CFW and Linux-state workflows remain container-only")
    policy = manifest.compatibility
    if policy.get("arch", "win64") != "win64" or policy.get("graphics", {}).get("backend", "wined3d") not in {"wined3d", "none", "auto"}:
        raise DesktopError("desktop POC supports win64 prefixes and builtin Wine graphics only")
    env = {**compatibility_environment(policy), **manifest.launch.env}
    for key in env:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise DesktopError("invalid desktop environment key")
        if key in {"PATH", "WINEPREFIX", "WINE", "WINESERVER", "WINELOADER", "HOME", "FLATPAK_ID"} or key.startswith(("LD_", "DYLD_", "XDG_")):
            raise DesktopError(f"desktop environment key is runtime-owned: {key}")
    if "WINEARCH" in manifest.launch.env:
        raise DesktopError("launch.env cannot override desktop WINEARCH")
    return target


def normalize_seed(prefix):
    """Remove only generated build-host mappings from a fresh build prefix."""
    prefix = Path(prefix)
    for path in (prefix / "dosdevices").iterdir():
        if path.name != "c:":
            if not path.is_symlink():
                raise DesktopError(f"unexpected Wine drive object: {path}")
            path.unlink()
    for path in (prefix / "drive_c/users").glob("*/*"):
        if path.is_symlink() and os.path.isabs(os.readlink(path)):
            if path.name not in {"Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos", "Templates"}:
                raise DesktopError(f"unexpected generated user link: {path}")
            path.unlink()
            path.mkdir()
    return inventory_tree(prefix)


def seal_desktop_bundle(bundle, target, runtime_evidence):
    bundle = Path(bundle)
    inventory = normalize_seed(bundle / "prefix")
    receipt = {"schemaVersion": "cage.desktop-build/v0", "target": target,
               "seedDigest": digest_json(inventory), "inventory": inventory,
               "manifestDigest": digest_json(json.loads((bundle / "manifest.cage.json").read_text())),
               "runtimeEvidence": runtime_evidence,
               "qualification": "built-with-target-runtime; application workflow proof is separate"}
    (bundle / "metadata/desktop-build.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def create_desktop_export_plan(bundle):
    bundle = Path(bundle).resolve()
    verification = verify_bundle(bundle)
    if not verification.get("valid") or not verification.get("runnable"):
        raise DesktopError("desktop export requires a verified, materialized application bundle")
    payload = json.loads((bundle / "manifest.cage.json").read_text())
    parse_payload = {**payload}
    if "compatibility" in parse_payload:
        parse_payload["compatibility"] = {k: v for k, v in parse_payload["compatibility"].items() if k != "schemaVersion"}
    manifest = Manifest.from_dict(parse_payload)
    target = validate_desktop_recipe(manifest)
    if declared_outputs(bundle):
        raise DesktopError("absolute Linux-state outputs are not portable desktop assets")
    path = bundle / "metadata/desktop-build.json"
    if path.is_symlink() or not path.is_file():
        raise DesktopError("bundle has no qualified desktop build; rebuild with cage build --target flatpak")
    receipt = json.loads(path.read_text())
    if receipt.get("schemaVersion") != "cage.desktop-build/v0" or receipt.get("target") != target:
        raise DesktopError("desktop runtime target mismatch")
    if receipt.get("manifestDigest") != digest_json(manifest.to_dict()):
        raise DesktopError("desktop recipe changed after build")
    inventory = receipt.get("inventory", [])
    if not inventory or digest_json(inventory) != receipt.get("seedDigest"):
        raise DesktopError("desktop inventory seal is invalid")
    verify_inventory(bundle / "prefix", inventory)
    executable = windows_path(bundle / "prefix", manifest.launch.entrypoint)
    if not executable.is_file():
        raise DesktopError("desktop entrypoint is missing")
    with executable.open("rb") as handle:
        header = handle.read(64)
        if header[:2] != b"MZ" or len(header) < 64:
            raise DesktopError("desktop entrypoint is not a Windows PE executable")
        handle.seek(int.from_bytes(header[60:64], "little"))
        if handle.read(6) != b"PE\0\0\x64\x86":
            raise DesktopError("desktop POC entrypoint must be an x86_64 Windows executable")
    return {"schemaVersion": "cage.desktop-export-plan/v0", "application": {"name": manifest.name, "version": manifest.version},
            "desktop": manifest.desktop, "launch": manifest.launch.to_dict(),
            "environment": {**compatibility_environment(manifest.compatibility), **manifest.launch.env},
            "target": target, "seedDigest": receipt["seedDigest"],
            "sourceManifestDigest": receipt["manifestDigest"],
            "state": {"schemaVersion": "cage.desktop-state/v0", "upgradePolicy": "refuse-mismatch-retain-data"},
            "qualification": receipt["qualification"]}
