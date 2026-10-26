"""Minimal local .app export over Cage's sealed native bundle and state contract."""
from __future__ import annotations

import json
from pathlib import Path
import plistlib
import shutil
import subprocess

from artifact.appimage import unpack_python
from artifact.inspection import verify_bundle
from artifact.macos import read_manifest
from artifact.storage import build_lock
from runtime.desktop_launch import DesktopError, digest_json, inventory_tree
from runtime.macos import api, command, download, require_host, sha256, verify_runtime, write
from runtime.macos_launch import run_plan

ROOT = Path(__file__).resolve().parents[1]


def tools_lock():
    return json.loads((ROOT / "runtime/macos-app-tools.json").read_text())


def create_macos_app_plan(bundle, *, allow_host_access=False, store=None, state_dir=None):
    source = run_plan(bundle, store=store, state_dir=state_dir, allow_host_access=allow_host_access)
    return {"schemaVersion": "cage.macos-app-export/v0", "format": "macos-app", "sourceBundle": source["bundle"],
            "contract": source["contract"], "tools": tools_lock(),
            "config": {"schemaVersion": "cage.macos-app/v0", "allowHostAccess": True, "identity": source["identity"],
                       "runtimeStore": source["runtimeStore"] if store is not None else None,
                       "stateParent": str(Path(state_dir).absolute()) if state_dir is not None else None},
            "prerequisites": ["Apple Silicon macOS 15+", "previously verified pinned MetalSharp-Wine cache"],
            "distribution": "local ad-hoc integrity signing; no Developer ID, notarization or redistribution clearance"}


def verify_python_metadata(lock, release, tag):
    asset = next((a for a in release["assets"] if a["name"] == lock["asset"]["name"]), {})
    expected = lock["asset"]
    if (release["id"] != lock["releaseId"] or release["tag_name"] != lock["tag"]
            or release.get("draft") or release.get("prerelease")
            or tag != {"type": "commit", "sha": lock["sourceCommit"]}
            or asset.get("id") != expected["id"] or asset.get("size") != expected["size"]
            or asset.get("digest") != "sha256:" + expected["sha256"]
            or asset.get("browser_download_url") != expected["url"]):
        raise DesktopError("standalone macOS Python publisher identity mismatch")


def stage_bundle(bundle, destination):
    """Keep the verifiable bundle; exclude build homes, downloads and inputs."""
    bundle, destination = Path(bundle), Path(destination)
    destination.mkdir()
    shutil.copy2(bundle / "manifest.cage.json", destination)
    for directory in ("prefix", "metadata", "runtime", "launch", "logs"):
        inventory_tree(bundle / directory)
        shutil.copytree(bundle / directory, destination / directory, symlinks=True)
    (destination / "build").mkdir()
    for file in (bundle / "build").iterdir():
        if file.is_file() and not file.is_symlink() and file.suffix in {".json", ".sh"}:
            shutil.copy2(file, destination / "build" / file.name)
    verified = verify_bundle(destination)
    if not verified["valid"] or not verified["runnable"]:
        raise DesktopError("packaged source bundle failed verification: " + "; ".join(verified["errors"]))


def stage_cage(destination):
    # A small source snapshot reuses the original verifier/lifecycle, with no
    # host Cage installation, checkout, Python site packages or import resolver.
    for directory in ("artifact", "builder", "core", "runtime"):
        for source in sorted((ROOT / directory).rglob("*")):
            if source.suffix not in {".py", ".json"} or "__pycache__" in source.parts:
                continue
            if source.is_symlink() or not source.is_file():
                raise DesktopError("linked or special Cage source rejected")
            target = destination / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return inventory_tree(destination)


def export_macos_app(bundle, *, output, allow_host_access=False, store=None, state_dir=None,
                     cache=".cage/macos-app-tools"):
    require_host()
    plan = create_macos_app_plan(bundle, allow_host_access=allow_host_access, store=store, state_dir=state_dir)
    verify_runtime(run_plan(bundle, store=store, allow_host_access=True)["runtimeStore"])
    output = Path(output).absolute()
    if output.suffix != ".app":
        raise DesktopError("native application output must end in .app")
    with build_lock(output):
        if output.exists() or output.is_symlink():
            raise DesktopError("application output already exists; existing package retained")
        context = Path(str(output) + ".build")
        context.mkdir()
        contents = output / "Contents"
        resources = contents / "Resources"
        resources.mkdir(parents=True)
        (contents / "MacOS").mkdir()
        desktop = plan["contract"]["desktop"]
        info = {"CFBundlePackageType": "APPL", "CFBundleExecutable": "CageLauncher",
                "CFBundleIdentifier": desktop["id"], "CFBundleName": desktop["name"],
                "CFBundleShortVersionString": plan["contract"]["application"]["version"], "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "15.0", "LSArchitecturePriority": ["arm64"],
                "NSHighResolutionCapable": True, "LSUIElement": True,
                "CFBundleDocumentTypes": [{"CFBundleTypeName": association["entrypoint"], "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate", "CFBundleTypeExtensions": [ext.lstrip(".") for ext in association.get("extensions", [])],
                    "CFBundleTypeMIMETypes": association.get("mime", [])}
                    for association in read_manifest(plan["sourceBundle"]).file_associations]}
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        write(resources / "app-config.json", plan["config"])
        stage_bundle(plan["sourceBundle"], resources / "application")
        code = stage_cage(resources / "cage-code")
        shutil.copy2(ROOT / "runtime/macos_app_entry.py", resources / "entry.py")
        lock = plan["tools"]
        repo = "repos/" + lock["repository"]
        release = api(repo + "/releases/" + str(lock["releaseId"]))
        tag = api(repo + "/git/ref/tags/" + lock["tag"])["object"]
        verify_python_metadata(lock, release, {key: tag[key] for key in ("type", "sha")})
        write(context / "python-publisher.json", {"release": release, "tag": tag})
        cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
        archive = download(lock["asset"]["url"], cache / lock["asset"]["sha256"],
                           lock["asset"]["sha256"], lock["asset"]["size"])
        unpack_python(archive, resources)
        python = resources / "python/bin/python3.13"
        command([python, "-I", "-B", "--version"], context / "python-version.txt")
        if (context / "python-version.txt").read_text().strip() != "Python " + lock["pythonVersion"]:
            raise DesktopError("packaged Python version mismatch")
        if subprocess.check_output(["lipo", "-archs", python], text=True).strip() != "arm64":
            raise DesktopError("packaged Python is not native ARM64")
        notices = resources / "NOTICE.txt"
        notices.write_text("Local Cage .app proof; ordinary user host access.\n"
            "Cage source: https://github.com/Pelagians/Cage (project metadata declares MIT).\n"
            "The exact Cage source snapshot is retained in cage-code/.\n"
            "CPython source/build: https://github.com/" + lock["repository"] + "/tree/" + lock["sourceCommit"] + "\n"
            "CPython archive SHA-256: " + lock["asset"]["sha256"] + "\n"
            "All bundled Python notices remain under python/, including lib/python3.13/LICENSE.txt.\n"
            "Application source/license identity remains in application/manifest.cage.json and its prefix notices.\n"
            "MetalSharp-Wine is not embedded or republished; launch verifies the existing pinned cache.\n"
            "Ad-hoc integrity signing is not Developer ID/notarization or redistribution clearance.\n")
        write(resources / "package.json", {"plan": plan, "cageCodeDigest": digest_json(code),
              "launcherSourceSha256": sha256(ROOT / "runtime/macos_app.m")})
        command(["xcrun", "clang", "-arch", "arm64", "-mmacosx-version-min=15.0", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                 "-framework", "AppKit", ROOT / "runtime/macos_app.m", "-o", contents / "MacOS/CageLauncher"], context / "compile.log")
        command(["codesign", "--force", "--sign", "-", "--timestamp=none", output], context / "sign.log")
        command([contents / "MacOS/CageLauncher", "--cage-verify"], context / "signature-verification.log")
        inventory = inventory_tree(output)
        result = {"schemaVersion": "cage.macos-app-export-result/v0", "success": True, "output": str(output),
                  "plan": plan, "inventoryDigest": digest_json(inventory), "inventory": inventory,
                  "signature": "ad-hoc; local integrity only", "runtimeEmbedded": False}
        write(Path(str(output) + ".json"), result)
        return result
