"""Flatpak layout and assembly over the shared desktop contract."""
from __future__ import annotations

from artifact.storage import build_lock, record_export

import hashlib
import json
import re
from pathlib import Path
import shutil
from xml.sax.saxutils import escape

from artifact.desktop import create_desktop_export_plan, stage_desktop_fonts
from builder.flatpak import ensure_target, initialize_flatpak, run_flatpak
from runtime import desktop_launch
from runtime.desktop_launch import DesktopError, verify_inventory, digest_json, copy_file

ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128"><rect x="8" y="8" width="112" height="112" rx="20" fill="#245b78"/><path d="M38 30h40l16 16v52H38z" fill="#fff"/><path d="M48 58h34M48 70h34M48 82h24" stroke="#245b78" stroke-width="5"/></svg>\n'


def create_flatpak_export_plan(bundle):
    plan = create_desktop_export_plan(bundle)
    return {**plan, "format": "flatpak", "branch": "stable",
            "state": {**plan["state"], "packagerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "layout": {"runtime": "/app"},
            "permissions": ["--unshare=network", "--share=ipc", "--socket=x11",
                            "--filesystem=xdg-documents/" + plan["desktop"]["documentsDirectory"] + ":create"],
            "prerequisites": ["Flatpak", plan["target"]["platform"] + "//" + plan["target"]["branch"]],
            "distribution": "local proof of concept; unsigned; no publication performed"}


def prepare_flatpak_context(bundle, plan, context, *, store):
    context = Path(context).resolve()
    if context.is_relative_to(Path(bundle).resolve()):
        raise DesktopError("export staging must be outside the source bundle")
    if context.exists():
        raise DesktopError(f"Flatpak export context already exists: {context}")
    context.mkdir(parents=True)
    build_dir = context / "app"
    initialize_flatpak(build_dir, plan["desktop"]["id"], plan["target"], store)
    files = build_dir / "files"
    location = run_flatpak(['info', '--user', '--show-location',
                           plan['target']['platform'] + '/' + plan['target']['architecture'] + '/' + plan['target']['branch']], store=store)
    stage_desktop_fonts(files, Path(location) / 'files')
    destination = files / "share/cage" / plan["desktop"]["id"]
    destination.mkdir(parents=True)
    receipt = json.loads((Path(bundle) / "metadata/desktop-build.json").read_text())
    if digest_json(receipt["inventory"]) != plan["seedDigest"]:
        raise DesktopError("source inventory changed after export planning")
    shutil.copytree(Path(bundle) / "prefix", destination / "seed", symlinks=True, copy_function=copy_file)
    verify_inventory(destination / "seed", receipt["inventory"])
    (destination / "seed-inventory.json").write_text(json.dumps(receipt["inventory"], sort_keys=True) + "\n")
    (destination / "desktop.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    manifest = json.loads((Path(bundle) / "manifest.cage.json").read_text())
    if digest_json(manifest) != plan["sourceManifestDigest"]:
        raise DesktopError("source manifest changed after export planning")
    (destination / "manifest.cage.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (destination / "component-sources.json").write_text(json.dumps({
        "applicationSources": manifest.get("sources", []),
        "applicationLicense": plan["desktop"]["license"],
        "wineBuildSource": plan["target"]["baseSource"],
        "wineBuildCommit": plan["target"].get("baseCommit"),
        "runtimePackages": plan["target"].get("packages", []),
        "notice": "Preserve application/runtime notices and provide corresponding source before redistribution."
    }, indent=2, sort_keys=True) + "\n")
    helper = files / "libexec/cage-desktop-launch.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(desktop_launch.__file__, helper)
    if hashlib.sha256(helper.read_bytes()).hexdigest() != plan["state"]["launcherSha256"]:
        raise DesktopError("lifecycle helper changed after export planning")
    wrapper = files / "bin/cage-desktop-launch"
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 -I /app/libexec/cage-desktop-launch.py /app/share/cage/'
                       + plan["desktop"]["id"] + '/desktop.json "$@"\n')
    wrapper.chmod(0o755)
    desktop = plan["desktop"]
    entries = files / "share/applications"
    entries.mkdir(parents=True, exist_ok=True)
    (entries / (desktop["id"] + ".desktop")).write_text(
        desktop_launch.desktop_entry(plan, 'cage-desktop-launch -- %F'))
    icon = files / "share/icons/hicolor/scalable/apps" / (desktop["id"] + ".svg")
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_text(ICON)
    metadata = files / "share/metainfo" / (desktop["id"] + ".metainfo.xml")
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<component type="desktop-application">'
                        f'<id>{desktop["id"]}</id><metadata_license>CC0-1.0</metadata_license>'
                        f'<project_license>{escape(desktop["license"])}</project_license>'
                        f'<name>{escape(desktop["name"])}</name><summary>{escape(desktop["summary"])}</summary>'
                        f'<url type="homepage">{escape(desktop["homepage"])}</url>'
                        f'<launchable type="desktop-id">{desktop["id"]}.desktop</launchable>'
                        '<description><p>A Windows application packaged with Cage and Wine.</p></description></component>\n')
    (context / "export-plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    return build_dir


def export_flatpak(bundle, *, output, store, context_dir=None, timeout=900):
    plan = create_flatpak_export_plan(bundle)
    output = Path(output).resolve()
    if output.is_relative_to(Path(bundle).resolve()):
        raise DesktopError("export output must be outside the source bundle")
    if output.exists() or Path(str(output) + ".partial").exists():
        raise DesktopError(f"Flatpak output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    context = Path(context_dir).resolve() if context_dir else output.parent / (output.name + ".build")
    with build_lock(context):
        ensure_target(plan["target"], store)
        build_dir = prepare_flatpak_context(bundle, plan, context, store=store)
        run_flatpak(["build-finish", "--no-inherit-permissions", "--command=cage-desktop-launch",
                     *plan["permissions"], str(build_dir)], store=store, timeout=timeout)
        repo = context.resolve() / "repository"
        run_flatpak(["build-export", str(repo), str(build_dir), "stable"], store=store, timeout=timeout)
        commit = (repo / 'refs/heads/app' / plan['desktop']['id'] / plan['target']['architecture'] / 'stable').read_text().strip()
        if not re.fullmatch('[a-f0-9]{64}', commit):
            raise DesktopError('Flatpak repository returned an invalid application commit')
        temporary = Path(str(output) + ".partial")
        run_flatpak(["build-bundle", "--runtime-repo=" + plan["target"]["remoteUrl"],
                     str(repo), str(temporary), plan["desktop"]["id"], "stable"], store=store, timeout=timeout)
        temporary.replace(output)
        with output.open("rb") as handle:
            h = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        result = {"schemaVersion": "cage.flatpak-export-result/v0", "success": True, "output": str(output),
                  "sha256": h.hexdigest(), "bytes": output.stat().st_size, "context": str(context.resolve()), "plan": plan,
                  "commit": commit}
        Path(str(output) + ".json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        result['storage'] = record_export(context, bundle, 'flatpak', {'kind': 'file', 'path': str(output), 'sha256': result['sha256']})
        return result
