"""Small, stdlib-only desktop launch contract, also shipped inside exports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


class DesktopError(ValueError):
    pass


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inventory_tree(root):
    """Hash all bytes and metadata, rejecting special files and escaping links."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise DesktopError(f"payload root must be a real directory: {root}")
    result = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        item = {"path": path.relative_to(root).as_posix(), "mode": stat.S_IMODE(info.st_mode)}
        if info.st_mode & 0o6000:
            raise DesktopError(f"set-ID payload member: {path}")
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            if os.path.isabs(target) or not path.resolve().is_relative_to(root.resolve()):
                raise DesktopError(f"escaping payload symlink: {path}")
            if not path.exists():
                raise DesktopError(f"dangling payload symlink: {path}")
            item.update(type="symlink", target=target)
        elif stat.S_ISDIR(info.st_mode):
            item["type"] = "directory"
        elif stat.S_ISREG(info.st_mode):
            h = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(chunk)
            item.update(type="file", bytes=info.st_size, sha256=h.hexdigest())
        else:
            raise DesktopError(f"special payload member: {path}")
        result.append(item)
    return result


def verify_inventory(root, inventory):
    if inventory_tree(root) != inventory:
        raise DesktopError("desktop payload inventory mismatch; rebuild from trusted inputs")


def windows_path(prefix, value):
    normalized = value.replace("\\", "/")
    if not normalized.lower().startswith("c:/"):
        raise DesktopError("desktop executable/working directory must use an absolute C: path")
    parts = normalized[3:].split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise DesktopError("unsafe Windows application path")
    path = Path(prefix) / "drive_c"
    for part in parts:
        direct = path / part
        if not direct.exists() and path.is_dir():
            matches = [p for p in path.iterdir() if p.name.casefold() == part.casefold()]
            if len(matches) == 1:
                direct = matches[0]
        path = direct
    if not path.resolve().is_relative_to((Path(prefix) / "drive_c").resolve()):
        raise DesktopError("Windows application path escapes its prefix")
    return path


def _write_state_record(path, identity):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".state-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(identity, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def initialize_state(seed, inventory, state_root, identity):
    """Copy once under a lock and atomically commit; never migrate an old prefix."""
    import fcntl
    seed, root = Path(seed), Path(state_root)
    if root.is_symlink():
        raise DesktopError("application state directory cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / "initialize.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prefix, partial, record = root / "prefix", root / "prefix.partial", root / "state.json"
        if any(p.is_symlink() for p in (prefix, partial, record)):
            raise DesktopError("linked state paths are unsupported")
        if record.exists():
            if json.loads(record.read_text()) != identity:
                raise DesktopError("state belongs to a different seed/runtime; previous data retained; migration is not implemented")
            if not (prefix / "drive_c").is_dir():
                raise DesktopError("persistent prefix is incomplete; restore it before launching")
            return prefix
        # An interrupted promotion without its record is not treated as valid state.
        if prefix.exists():
            marker = prefix / ".cage-state.json"
            if marker.is_file() and not marker.is_symlink() and json.loads(marker.read_text()) == identity:
                # The directory promotion committed; only its external receipt
                # was interrupted. Recover without replacing the prefix.
                _write_state_record(record, identity)
                return prefix
            raise DesktopError("uncommitted prefix retained; move it aside for recovery before retrying")
        if partial.exists():
            shutil.rmtree(partial)
        verify_inventory(seed, inventory)
        try:
            shutil.copytree(seed, partial, symlinks=True)
            verify_inventory(partial, inventory)
            (partial / ".cage-state.json").write_text(json.dumps(identity, sort_keys=True) + "\n")
            partial.rename(prefix)
            _write_state_record(record, identity)
        except BaseException:
            if partial.exists():
                shutil.rmtree(partial)
            raise
        return prefix


def launch(metadata_path, files):
    metadata_path = Path(metadata_path)
    plan = json.loads(metadata_path.read_text())
    page_sizes = plan["target"].get("translation", {}).get("hostPageSizes")
    if page_sizes and os.sysconf("SC_PAGE_SIZE") not in page_sizes:
        raise DesktopError("Wine/FEX runtime does not qualify this kernel page size")
    inventory = json.loads((metadata_path.parent / "seed-inventory.json").read_text())
    if digest_json(inventory) != plan["seedDigest"]:
        raise DesktopError("seed inventory digest mismatch")
    # Flatpak sets per-app XDG_DATA_HOME; future adapters provide their own base.
    state_root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    namespace = plan.get("state", {}).get("namespace")
    if namespace:
        if namespace != "cage/appimage":
            raise DesktopError("unsupported desktop state namespace")
        state_root /= namespace
    state_root /= plan["desktop"]["id"]
    identity = {"schemaVersion": "cage.desktop-state/v0", "seedDigest": plan["seedDigest"],
                "runtimeDigest": digest_json(plan["target"])}
    seed = Path(plan["layout"]["seed"]) if plan["layout"].get("seed") else metadata_path.parent / "seed"
    prefix = initialize_state(seed, inventory, state_root, identity)
    runtime_root = Path(plan["layout"]["runtime"])
    if plan.get("format") == "appimage":
        # AppImage mounts and extracted AppDirs relocate between launches.
        runtime_root = metadata_path.parents[3] / "wine"
    wine = str(runtime_root / plan["target"]["wine"])
    server = str(runtime_root / plan["target"]["wineserver"])
    environment = {k: v for k, v in os.environ.items() if not (
        k.startswith(("WINE", "LD_", "DYLD_")) or k in {"PROTONPATH", "STEAM_COMPAT_DATA_PATH"}
    )}
    environment.update(plan["environment"])
    environment.update(WINEPREFIX=str(prefix), WINEARCH="win64")
    if plan.get("format") == "appimage":
        usr = metadata_path.parents[3]
        environment["LD_LIBRARY_PATH"] = str(usr / "lib/cage-native")
        environment["WINEDLLPATH"] = str(runtime_root / plan["target"]["wineDllDirectory"])
        environment["FONTCONFIG_FILE"] = str(usr / "share/cage/fonts.conf")
        environment["FONTCONFIG_PATH"] = str(usr / "share/cage")
        environment["XLOCALEDIR"] = str(usr / "share/X11/locale")
        environment["XKB_CONFIG_ROOT"] = str(usr / "share/X11/xkb")
    environment.setdefault("WINEDEBUG", "-all")
    environment.setdefault("WINEDLLOVERRIDES", "winemenubuilder.exe=d;mscoree,mshtml=")
    if plan["target"]["graphics"] == "x11":
        environment.pop("WAYLAND_DISPLAY", None)
        environment.pop("WAYLAND_SOCKET", None)
    # This maps the Flatpak namespace, not an unrestricted host filesystem.
    zdrive = prefix / "dosdevices/z:"
    if not zdrive.exists() and not zdrive.is_symlink():
        zdrive.symlink_to("/")
    arguments = []
    for name in files:
        path = Path(name).absolute()
        if not path.is_file():
            raise DesktopError(f"file is missing or inaccessible with this package's permissions: {path}")
        arguments.append("Z:" + str(path).replace("/", "\\"))
    contract = plan["launch"]
    executable = windows_path(prefix, contract["entrypoint"])
    if not executable.is_file():
        raise DesktopError("application executable is missing from persistent state")
    cwd = windows_path(prefix, contract["workingDirectory"]) if contract.get("workingDirectory") else executable.parent
    if not cwd.is_dir():
        raise DesktopError("application working directory is missing")
    return _run_application([wine, contract["entrypoint"], *contract.get("args", []), *arguments],
                            server, environment, cwd, state_root)


def _run_application(command, server, environment, cwd, state_root):
    """Own one prefix lifecycle; Wine services must not outlive its GUI app."""
    import fcntl
    descriptor = os.open(state_root / "launch.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DesktopError("this application is already running; close it before launching another instance") from exc
        try:
            return subprocess.run(command, env=environment, cwd=cwd).returncode
        finally:
            # WINEPREFIX scopes this to the application. The launch lock prevents
            # terminating another legitimate Cage launch in the same prefix.
            subprocess.run([server, "-k"], env=environment, timeout=15, check=False)
            subprocess.run([server, "-w"], env=environment, timeout=30, check=True)


if __name__ == "__main__":
    try:
        raise SystemExit(launch(sys.argv[1], sys.argv[2:]))
    except (DesktopError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Cage desktop launch failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
