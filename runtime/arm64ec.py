"""Pinned native Wine/FEX payload shared by Flatpak and OCI adapters."""
from __future__ import annotations

import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import urllib.request

from runtime.desktop_launch import DesktopError, inventory_tree, verify_inventory, copy_file

LOCK = Path(__file__).with_name("wine-arm64ec-11.20-fex-2610.json")


def runtime_target():
    return json.loads(LOCK.read_text())


def existing_runtime_target(target):
    """Read/launch old sealed bundles without changing their runtime identity.

    Producers still use runtime_target(). Only the exact previously shipped
    pin is accepted here; this does not permit cross-runtime prefix migration.
    """
    if target == runtime_target():
        return target
    previous = json.loads((LOCK.parent / 'legacy/wine-arm64ec-11.20-fex-2610.json').read_text())
    if target == previous:
        return target
    raise DesktopError('unknown ARM64EC runtime identity; retained state was not changed')


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_termination_guard(root):
    """Replace one verified RPM DLL; the compiler is build/reproduction-only."""
    target = runtime_target()
    patch = target['translation']['terminationGuard']
    vendor = Path(__file__).parent / 'vendor/fex-2610-cage1'
    source = vendor / 'source.json'
    if sha256_file(source) != patch['sourceSha256']:
        raise DesktopError('FEX source/build identity mismatch')
    record = json.loads(source.read_text())['dll']
    archive = vendor / 'libarm64ecfex.dll.xz'
    if sha256_file(archive) != record['compressedSha256']:
        raise DesktopError('FEX termination guard archive checksum mismatch')
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024**2)
    data = decoder.decompress(archive.read_bytes(), max_length=record['size'] + 1)
    if (not decoder.eof or decoder.unused_data or len(data) != record['size']
            or hashlib.sha256(data).hexdigest() != record['sha256']):
        raise DesktopError('FEX termination guard DLL checksum mismatch')
    destination = Path(root) / 'lib64/wine-wow64/wine/aarch64-windows/libarm64ecfex.dll'
    if destination.is_symlink() or not destination.is_file() or sha256_file(destination) != patch['rpmDllSha256']:
        raise DesktopError('FEX termination guard requires the exact pinned RPM DLL')
    temporary = destination.with_suffix('.dll.cage-new')
    try:
        with temporary.open('xb') as output:
            output.write(data)
        temporary.chmod(stat.S_IMODE(destination.stat().st_mode))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    notices = Path(root) / 'share/licenses/cage-fex-2610-cage1'
    notices.mkdir(parents=True, exist_ok=True)
    for original in (source, vendor / 'LICENSES.txt',
                     Path(__file__).parent / 'patches/fex-2610-process-termination.patch'):
        shutil.copyfile(original, notices / original.name)


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
    # Retain the original immutable cache: old export contexts may still use it.
    payload, receipt = cache / "files-fex-cage1", cache / "inventory-fex-cage1.json"
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
        base, base_receipt = cache / 'files', cache / 'inventory.json'
        reused = False
        if base.is_dir() and base_receipt.is_file():
            inventory = json.loads(base_receipt.read_text())
            if digest_json(inventory) == runtime_target()['rpmPayloadDigest']:
                verify_inventory(base, inventory)
                shutil.copytree(base, root, symlinks=True, dirs_exist_ok=True, copy_function=copy_file)
                reused = True
        for package in ([] if reused else packages):
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
        if not reused:
            for name, target in (("wine", "wine64"), ("wineserver", "wineserver64")):
                (root / "bin" / name).symlink_to(target)
        if digest_json(inventory_tree(root)) != runtime_target()['rpmPayloadDigest']:
            raise DesktopError('extracted ARM runtime differs from pinned RPM payload')
        install_termination_guard(root)
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
    install_termination_guard('/usr')


def verify_container_runtime(engine, image, *, execution_target=None):
    from runtime.desktop_launch import digest_json
    target = existing_runtime_target(execution_target) if execution_target is not None else runtime_target()
    result = subprocess.run([engine, "image", "inspect", image], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise DesktopError("cannot inspect ARM64EC runtime image: " + image)
    data = json.loads(result.stdout)[0]
    labels = data.get("Config", {}).get("Labels", {}) or {}
    if data.get("Architecture") != "arm64" or labels.get("org.pelagian.cage.session-contract") != "cage.native-wine/v1" or labels.get("io.cage.runtime.target-sha256") != digest_json(target):
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
            "desktop": {**manifest.desktop, "id": manifest.desktop.get("id", manifest.name)},
            "application": {"name": manifest.name, "version": manifest.version},
            "launch": manifest.launch.to_dict() if manifest.launch else {},
            "seedDigest": digest_json(inventory), "sourceManifestDigest": digest_json(manifest.to_dict()),
            "environment": {**compatibility_environment(manifest.compatibility), **(manifest.launch.env if manifest.launch else {})},
            "layout": {"runtime": "/usr", "seed": "/opt/cage/bundle/prefix"}}
    (bundle / "metadata/seed-inventory.json").write_text(json.dumps(inventory, sort_keys=True) + "\n")
    import shutil
    from runtime import desktop_launch
    shutil.copyfile(desktop_launch.__file__, bundle / "metadata/cage-desktop-launch.py")
    plan["state"] = {"managerVersion": 1}
    plan["launcherSha256"] = hashlib.sha256((bundle / "metadata/cage-desktop-launch.py").read_bytes()).hexdigest()
    (bundle / "metadata/native-launch.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")


def native_launch_script(bundle, file_arguments, state_action=None):
    import shlex
    from runtime.desktop_launch import digest_json
    bundle = Path(bundle)
    plan = json.loads((bundle / "metadata/native-launch.json").read_text())
    inventory = json.loads((bundle / "metadata/seed-inventory.json").read_text())
    graph = json.loads((bundle / "metadata/graph.json").read_text())
    target = existing_runtime_target(graph['runnerRuntime'].get('executionTarget'))
    if (plan["target"] != {**target, "carrierImage": graph["runnerRuntime"]["image"]}
            or plan["seedDigest"] != digest_json(inventory)
            or plan["sourceManifestDigest"] != digest_json(json.loads((bundle / "manifest.cage.json").read_text()))):
        raise DesktopError("native container seed/runtime/recipe seal mismatch; rebuild with the selected ARM runtime")
    helper = bundle / "metadata/cage-desktop-launch.py"
    if plan.get("launcherSha256") and (helper.is_symlink() or not helper.is_file() or hashlib.sha256(helper.read_bytes()).hexdigest() != plan["launcherSha256"]):
        raise DesktopError("native lifecycle helper seal mismatch")
    launcher = "/opt/cage/bundle/metadata/cage-desktop-launch.py" if plan.get("launcherSha256") else "/usr/lib/cage-runtime/runtime/desktop_launch.py"
    if state_action and not plan.get("launcherSha256"):
        raise DesktopError("rebuild the bundle to enable safe update/rollback controls")
    verify_inventory(bundle / "prefix", inventory)
    if state_action == "state-info" and file_arguments:
        raise DesktopError("state-info does not open application documents")
    arguments = " ".join(shlex.quote(a) for a in
                         (["--cage-" + state_action] if state_action else [])
                         + (["--"] if plan.get("state", {}).get("managerVersion") == 1 and state_action != "state-info" else []) + file_arguments)
    return ('export XDG_DATA_HOME="${CAGE_STATE:-/var/lib/cage/state}"\n'
            'exec /usr/bin/python3 -I ' + launcher + ' '
            '/opt/cage/bundle/metadata/native-launch.json ' + arguments + '\n')


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--container-install"]:
        install_container_runtime("/tmp/cage-arm-rpms")
