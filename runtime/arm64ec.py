"""Pinned native Wine/FEX payload shared by Flatpak and OCI adapters."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import urllib.request

from runtime.desktop_launch import DesktopError, inventory_tree, verify_inventory

LOCK = Path(__file__).with_name("wine-arm64ec-11.20-fex-2610.json")


def runtime_target():
    return json.loads(LOCK.read_text())


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire_packages(cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    result = []
    for package in runtime_target()["packages"]:
        path = cache / package["url"].rsplit("/", 1)[1]
        if not path.exists():
            temporary = path.with_suffix(".partial")
            try:
                with urllib.request.urlopen(package["url"], timeout=120) as response, temporary.open("wb") as out:
                    total = 0
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        total += len(chunk)
                        if total > 512 * 1024**2:
                            raise DesktopError("ARM runtime package exceeds download limit")
                        out.write(chunk)
                if sha256_file(temporary) != package["sha256"]:
                    raise DesktopError("ARM runtime package checksum mismatch: " + path.name)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        if path.is_symlink() or sha256_file(path) != package["sha256"]:
            raise DesktopError("ARM runtime package checksum mismatch: " + path.name)
        result.append(path)
    return result


def extract_cpio(stream, root):
    """Extract the RPM newc stream with bounded size and contained paths/links."""
    root = Path(root)
    links, total = {}, 0
    while True:
        header = stream.read(110)
        if len(header) != 110 or header[:6] not in (b"070701", b"070702"):
            raise DesktopError("invalid RPM cpio stream")
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        inode, mode, _, _, count, _, size, major, minor, _, _, name_size, _ = fields
        if not 1 <= name_size <= 4096:
            raise DesktopError("invalid cpio name length")
        raw_name = stream.read(name_size)
        if len(raw_name) != name_size or raw_name[-1:] != b"\0":
            raise DesktopError("invalid cpio name")
        name = raw_name[:-1].decode("utf-8")
        stream.read(-(110 + name_size) % 4)
        if name == "TRAILER!!!":
            return
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise DesktopError("unsafe RPM member path")
        total += size
        if total > 4 * 1024**3:
            raise DesktopError("RPM payload exceeds extraction limit")
        selected = (relative.as_posix() in {"usr/lib64", "usr/share"} or relative.parts[:2] == ("usr", "bin") or any(
            relative.is_relative_to(p) for p in ("usr/lib64/wine-wow64", "usr/share/wine", "usr/share/licenses")))
        path = root.joinpath(*relative.parts[1:])  # /usr becomes adapter's /app or /usr.
        if selected:
            if mode & 0o6000 or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
                raise DesktopError("unsafe RPM member mode or linked parent")
            path.parent.mkdir(parents=True, exist_ok=True)
        if selected and stat.S_ISREG(mode):
            key = (major, minor, inode)
            if count > 1 and key in links:
                if path.exists():
                    path.unlink()
                os.link(links[key], path)
            else:
                links[key] = path
            with path.open("r+b" if path.exists() else "wb") as output:
                remaining = size
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise DesktopError("truncated RPM member")
                    output.write(chunk)
                    remaining -= len(chunk)
            path.chmod(stat.S_IMODE(mode))
        else:
            if selected and size > 4096:
                raise DesktopError("invalid RPM directory/link size")
            remaining, data = size, b""
            while remaining:
                chunk = stream.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise DesktopError("truncated RPM member")
                if selected:
                    data += chunk
                remaining -= len(chunk)
            if selected and stat.S_ISDIR(mode):
                path.mkdir(exist_ok=True)
                path.chmod(stat.S_IMODE(mode))
            elif selected and stat.S_ISLNK(mode):
                target = data.decode("utf-8")
                if os.path.isabs(target) or not (path.parent / target).resolve().is_relative_to(root.resolve()):
                    raise DesktopError("escaping RPM symlink")
                path.symlink_to(target)
            elif selected:
                raise DesktopError("unsupported RPM member type")
        stream.read(-size % 4)


def materialize_payload(cache):
    """Build-only rpm2cpio is unnecessary on installed consumer systems."""
    import fcntl
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    fd = os.open(cache / "payload.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _materialize_payload(cache)


def _materialize_payload(cache):
    from runtime.desktop_launch import digest_json
    cache = Path(cache).resolve()
    packages = acquire_packages(cache / "packages")
    payload, receipt = cache / "files", cache / "inventory.json"
    if payload.exists():
        inventory = json.loads(receipt.read_text())
        if digest_json(inventory) != runtime_target()["payloadDigest"]:
            raise DesktopError("ARM runtime inventory does not match pinned payload identity")
        verify_inventory(payload, inventory)
        return payload
    if not shutil.which("rpm2cpio"):
        raise DesktopError("ARM runtime preparation requires rpm2cpio (build dependency only)")
    with tempfile.TemporaryDirectory(dir=cache) as td:
        root = Path(td) / "files"
        root.mkdir()
        for package in packages:
            with subprocess.Popen(["rpm2cpio", str(package)], stdout=subprocess.PIPE) as process:
                try:
                    extract_cpio(process.stdout, root)
                    # Drain padding so the producer cannot block on a full pipe.
                    while process.stdout.read(1024 * 1024):
                        pass
                except BaseException:
                    process.kill()
                    raise
                if process.wait(timeout=30):
                    raise DesktopError("rpm2cpio failed")
        for name, target in (("wine", "wine64"), ("wineserver", "wineserver64")):
            (root / "bin" / name).symlink_to(target)
        inventory = inventory_tree(root)
        if digest_json(inventory) != runtime_target()["payloadDigest"]:
            raise DesktopError("extracted ARM runtime payload differs from the pinned inventory")
        receipt.write_text(json.dumps(inventory, sort_keys=True) + "\n")
        root.rename(payload)
    return payload


def install_container_runtime(cache):
    """Use the same checked RPMs with distro dependency resolution inside OCI."""
    if os.uname().machine != "aarch64":
        raise DesktopError("Wine ARM64EC requires an aarch64 container")
    packages = acquire_packages(cache)
    subprocess.run(["dnf", "-y", "--setopt=install_weak_deps=False", "install", *map(str, packages)], check=True)


def verify_container_runtime(engine, image):
    from runtime.desktop_launch import digest_json
    result = subprocess.run([engine, "image", "inspect", image], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise DesktopError("cannot inspect ARM64EC runtime image: " + image)
    data = json.loads(result.stdout)[0]
    labels = data.get("Config", {}).get("Labels", {}) or {}
    if data.get("Architecture") != "arm64" or labels.get("org.pelagian.cage.session-contract") != "cage.native-wine/v1" or labels.get("io.cage.runtime.target-sha256") != digest_json(runtime_target()):
        raise DesktopError("ARM64EC image architecture, session contract or pinned Wine/FEX identity mismatch")


def seal_native_bundle(bundle, manifest, image):
    """Same immutable seed and first-use state contract as desktop exports."""
    from artifact.desktop import normalize_seed
    from core.compatibility import compatibility_environment
    from runtime.desktop_launch import digest_json
    bundle = Path(bundle)
    inventory = normalize_seed(bundle / "prefix")
    target = {**runtime_target(), "carrierImage": image}
    plan = {"schemaVersion": "cage.desktop-export-plan/v0", "target": target,
            "desktop": {"id": manifest.desktop.get("id", manifest.name)},
            "launch": manifest.launch.to_dict() if manifest.launch else {},
            "seedDigest": digest_json(inventory), "sourceManifestDigest": digest_json(manifest.to_dict()),
            "environment": {**compatibility_environment(manifest.compatibility), **(manifest.launch.env if manifest.launch else {})},
            "layout": {"runtime": "/usr", "seed": "/opt/cage/bundle/prefix"}}
    (bundle / "metadata/seed-inventory.json").write_text(json.dumps(inventory, sort_keys=True) + "\n")
    (bundle / "metadata/native-launch.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")


def native_launch_script(bundle, file_arguments):
    import shlex
    from runtime.desktop_launch import digest_json
    bundle = Path(bundle)
    plan = json.loads((bundle / "metadata/native-launch.json").read_text())
    inventory = json.loads((bundle / "metadata/seed-inventory.json").read_text())
    graph = json.loads((bundle / "metadata/graph.json").read_text())
    if (plan["target"] != {**runtime_target(), "carrierImage": graph["runnerRuntime"]["image"]}
            or plan["seedDigest"] != digest_json(inventory)
            or plan["sourceManifestDigest"] != digest_json(json.loads((bundle / "manifest.cage.json").read_text()))):
        raise DesktopError("native container seed/runtime/recipe seal mismatch; rebuild with the selected ARM runtime")
    verify_inventory(bundle / "prefix", inventory)
    arguments = " ".join(shlex.quote(a) for a in file_arguments)
    return ('export XDG_DATA_HOME="${CAGE_STATE:-/var/lib/cage/state}"\n'
            'exec /usr/bin/python3 -I /usr/lib/cage-runtime/runtime/desktop_launch.py '
            '/opt/cage/bundle/metadata/native-launch.json ' + arguments + '\n')


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--container-install"]:
        install_container_runtime("/tmp/cage-arm-rpms")
