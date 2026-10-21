"""Small, stdlib-only desktop launch contract, also shipped inside exports."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import re


def desktop_entry(plan, command, *, icon=None, suffix=''):
    """Shared desktop metadata; offer Open With without changing defaults."""
    desktop = plan['desktop']
    def value(text):
        return text.replace('\\', '\\\\')
    return ('[Desktop Entry]\nType=Application\nName=' + value(desktop['name']) + suffix
            + '\nComment=' + value(desktop['summary']) + '\nExec=' + command
            + '\nIcon=' + (icon or desktop['id']) + '\nCategories='
            + ';'.join(desktop['categories']) + ';\nTerminal=false\n'
            + ('MimeType=' + ';'.join(plan['mimeTypes']) + ';\n' if plan.get('mimeTypes') else ''))


def document_arguments(files):
    """Translate selected local files, including new files in accessible folders."""
    from urllib.parse import urlsplit, unquote
    arguments = []
    for name in files:
        if not name or any(ord(c) < 32 for c in name):
            raise DesktopError('document path must be a nonempty single-line path')
        if name.startswith('file:'):
            uri = urlsplit(name)
            if uri.netloc not in ('', 'localhost') or uri.query or uri.fragment or not uri.path.startswith('/'):
                raise DesktopError('only local file URIs are supported')
            name = unquote(uri.path)
        elif '://' in name:
            raise DesktopError('only local document paths are supported')
        path = Path(name).absolute()
        if any(ord(c) < 32 or c in '\\:*?"<>|' for c in str(path)):
            raise DesktopError('document path contains characters Wine cannot represent: ' + str(path))
        if path.exists():
            if not path.is_file() or not os.access(path, os.R_OK):
                raise DesktopError('document is not a readable file: ' + str(path))
        elif path.is_symlink() or not path.parent.is_dir() or not os.access(path.parent, os.W_OK):
            raise DesktopError('file is missing or inaccessible with this package\'s permissions: ' + str(path))
        arguments.append('Z:' + str(path).replace('/', '\\'))
    return arguments


def host_dpi():
    """Read the X11/XWayland logical DPI, never infer scale from physical size."""
    import ctypes
    try:
        xlib = ctypes.CDLL('libX11.so.6')
        xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        xlib.XResourceManagerString.argtypes = [ctypes.c_void_p]
        xlib.XResourceManagerString.restype = ctypes.c_char_p
        xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        display = xlib.XOpenDisplay(None)
        if not display:
            return 96
        try:
            resource = (xlib.XResourceManagerString(display) or b'').decode('utf-8', errors='replace')
        finally:
            xlib.XCloseDisplay(display)
        match = re.search(r'(?mi)^Xft[.*]dpi\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$', resource)
        return max(96, min(384, round(float(match[1])))) if match else 96
    except (OSError, ValueError):
        return 96


def display_preferences(root):
    path = _real_path(root, 'display.json')
    if path.exists() and not path.is_file():
        raise DesktopError('display preference is not a regular file; state retained')
    value = json.loads(path.read_text()) if path.exists() else {'dpi': 'auto'}
    if not isinstance(value, dict) or set(value) != {'dpi'} or not (value['dpi'] in ('auto', 'preserve') or
            type(value['dpi']) is int and 96 <= value['dpi'] <= 384):
        raise DesktopError('invalid display preference; state retained')
    return value


def prefix_dpi(prefix):
    path = _real_path(prefix, 'user.reg')
    if not path.is_file():
        return None
    content = path.read_text(errors='replace')
    section = re.search(r'(?m)^\[Control Panel\\\\Desktop\][^\n]*\n([^\[]*)', content)
    match = re.search(r'(?m)^"LogPixels"=dword:([a-fA-F0-9]+)$', section[1]) if section else None
    return int(match[1], 16) if match else None


def configure_fonts(plan, prefix, wine, server, environment, root, lock_fd):
    if not plan.get('display'):
        return
    # Wine's GDI family enumeration does not use fontconfig aliases as Windows
    # font names. Replacements apply only when the real family is absent; keep
    # all existing user replacements and application font preferences.
    replacements = {'Courier New': 'Liberation Mono', 'Consolas': 'DejaVu Sans Mono',
                    'Lucida Console': 'DejaVu Sans Mono', 'Arial': 'Liberation Sans',
                    'Times New Roman': 'Liberation Serif', 'Tahoma': 'DejaVu Sans',
                    'MS Sans Serif': 'Liberation Sans', 'Segoe UI': 'Carlito'}
    registry = _real_path(prefix, 'user.reg')
    content = registry.read_text(errors='replace') if registry.exists() else ''
    section = re.search(r'(?m)^\[Software\\\\Wine\\\\Fonts\\\\Replacements\][^\n]*\n([^\[]*)', content)
    existing = {name.casefold() for name in re.findall(r'(?m)^"([^"]+)"=', section[1])} if section else set()
    missing = {name: target for name, target in replacements.items() if name.casefold() not in existing}
    if not missing:
        return
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-16', suffix='.reg',
                                     dir=_real_path(prefix, 'drive_c'), delete=False) as handle:
        path = Path(handle.name)
        handle.write('Windows Registry Editor Version 5.00\n\n[HKEY_CURRENT_USER\\Software\\Wine\\Fonts\\Replacements]\n')
        handle.writelines('"' + name + '"="' + target + '"\n' for name, target in missing.items())
    try:
        result = _run_application([wine, 'reg.exe', 'import', 'C:\\' + path.name], server,
                                 environment, prefix, root, locked=True, lock_fd=lock_fd)
        if result:
            raise DesktopError('could not configure missing font fallbacks; state retained')
    finally:
        path.unlink(missing_ok=True)


def configure_display(plan, root, prefix, wine, server, environment, lock_fd):
    if not plan.get('display'):
        return  # Container and older package launch contracts remain unchanged.
    preference = display_preferences(root)
    selected = preference['dpi']
    if selected == 'preserve':
        return
    current = prefix_dpi(prefix)
    marker = _real_path(prefix, '.cage-display.json')
    previous = json.loads(marker.read_text()).get('dpi') if marker.exists() else None
    if selected == 'auto' and current is not None and (
            previous is None and current != 96 or previous is not None and current != previous):
        # Preserve pre-existing custom Wine DPI, including through future updates.
        if not 96 <= current <= 384:
            _write_state_record(root / 'display.json', {'dpi': 'preserve'})
            return
        _write_state_record(root / 'display.json', {'dpi': current})
        selected = current
    desired = host_dpi() if selected == 'auto' else selected
    if current != desired:
        result = _run_application([wine, 'reg.exe', 'add', r'HKCU\Control Panel\Desktop',
                                  '/v', 'LogPixels', '/t', 'REG_DWORD', '/d', str(desired), '/f'],
                                 server, environment, prefix, root, locked=True, lock_fd=lock_fd)
        if result:
            raise DesktopError('could not configure Wine display DPI; application state retained')
    _write_state_record(marker, {'dpi': desired})


class DesktopError(ValueError):
    pass


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan_identity(plan):
    identity = {"schemaVersion": "cage.desktop-state/v0", "seedDigest": plan["seedDigest"],
                "runtimeDigest": digest_json(plan["target"])}
    if plan.get("state", {}).get("managerVersion") == 1:
        identity.update(schemaVersion="cage.desktop-state/v1", contractDigest=digest_json(plan))
    return identity



def inventory_tree(root, *, state_snapshot=False):
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
            if not state_snapshot and (os.path.isabs(target) or not path.resolve().is_relative_to(root.resolve())):
                raise DesktopError(f"escaping payload symlink: {path}")
            if not state_snapshot and not path.exists():
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


def _flush_tree(root):
    for path in [*Path(root).rglob('*'), Path(root)]:
        if path.is_symlink():
            continue
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def migration_space(root, source):
    """Conservative full-copy budget unless this actual source supports reflinks."""
    root, source = Path(root), Path(source)
    files = [p for p in source.rglob('*') if not p.is_symlink() and p.is_file()]
    logical = sum(p.stat().st_size for p in files)
    clone = False
    sample = next((p for p in files if p.stat().st_size), None)
    if sample:
        import fcntl
        with sample.open('rb') as src, tempfile.TemporaryFile(dir=root) as dst:
            try:
                fcntl.ioctl(dst.fileno(), 0x40049409, src.fileno())
                clone = True
            except OSError:
                pass
    reserve = 128 * 1024 * 1024
    required = reserve + (len(files) * 16384 if clone else logical)
    available = shutil.disk_usage(root).free
    if available < required:
        raise DesktopError('insufficient space for migration; old state retained (required '
                           + str(required) + ', available ' + str(available) + ' bytes)')
    return {'logicalBytes': logical, 'reflinkAvailable': clone, 'requiredFreeBytes': required,
            'availableBytes': available}


def snapshot_legacy(root, identity, *, reuse=True):
    """Under the lifecycle lock: retain and verify v0 state without following links.

    This is a recovery inventory, never a trusted export/seed inventory. Absolute
    Wine drive mappings are recorded literally, never traversed or promoted.
    """
    root = Path(root)
    record = _read_generations(root)
    if not record or len(record['generations']) != 1 or record['active'] != 'prefix':
        raise DesktopError('migration requires recorded legacy state; managed generations retained')
    old = _generation(record, 'prefix')['identity']
    if old.get('schemaVersion') != 'cage.desktop-state/v0' or identity.get('schemaVersion') != 'cage.desktop-state/v1':
        raise DesktopError('migration requires a recorded v0 prefix and a generation-aware baseline')
    if old.get('runtimeDigest') != identity.get('runtimeDigest'):
        raise DesktopError('runtime changes require separate migration qualification; all state retained')
    source = _real_path(root, 'prefix')
    inventory = inventory_tree(source, state_snapshot=True)
    journal = _real_path(root, 'legacy-migration.json')
    if reuse and journal.is_file():
        previous = json.loads(journal.read_text())
        backup = _real_path(root, previous['snapshot'])
        receipt = _real_path(backup, 'snapshot.json')
        if receipt.is_file():
            saved = json.loads(receipt.read_text())
            if (saved['identity'] == old and saved['targetIdentity'] == identity
                    and saved['inventory'] == inventory
                    and inventory_tree(backup / 'prefix', state_snapshot=True) == inventory
                    and (backup / 'state.json').read_bytes() == (root / 'state.json').read_bytes()):
                return backup
    space = migration_space(root, source)
    import uuid
    parent = _real_path(root, 'legacy-snapshots')
    parent.mkdir(mode=0o700, exist_ok=True)
    backup = parent / uuid.uuid4().hex
    backup.mkdir(mode=0o700)
    _write_state_record(journal, {'status': 'preparing', 'snapshot': str(backup.relative_to(root))})
    shutil.copytree(source, backup / 'prefix', symlinks=True, copy_function=copy_file)
    copy_file(root / 'state.json', backup / 'state.json')
    preference = _real_path(root, 'display.json')
    if preference.exists():
        display_preferences(root)
        copy_file(preference, backup / 'display.json')
    if (inventory_tree(backup / 'prefix', state_snapshot=True) != inventory
            or inventory_tree(source, state_snapshot=True) != inventory
            or _generation(_read_generations(backup), 'prefix')['identity'] != old):
        raise DesktopError('legacy snapshot changed during copying; all state retained')
    _write_state_record(backup / 'snapshot.json', {'schemaVersion': 'cage.legacy-snapshot/v1',
        'identity': old, 'targetIdentity': identity, 'inventory': inventory, 'space': space,
        'externalDocuments': 'not traversed or rewritten; retained in their host locations'})
    _flush_tree(backup)
    _write_state_record(journal, {'status': 'snapshotted', 'snapshot': str(backup.relative_to(root)),
                                'identity': old, 'targetIdentity': identity})
    return backup


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
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
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
            shutil.copytree(seed, partial, symlinks=True, copy_function=copy_file)
            verify_inventory(partial, inventory)
            (partial / ".cage-state.json").write_text(json.dumps(identity, sort_keys=True) + "\n")
            partial.rename(prefix)
            _write_state_record(record, identity)
        except BaseException:
            if partial.exists():
                shutil.rmtree(partial)
            raise
        return prefix


# Generations are private to one adapter/application state root. Package managers
# own package bytes; this transaction owns only mutable Windows state.
def validate_update_policy(policy):
    if not isinstance(policy, dict) or set(policy) != {"profile", "settings", "documents"}:
        raise DesktopError("desktop.updates requires profile, settings and documents")
    import re
    if not isinstance(policy["profile"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/v[0-9]+", policy["profile"]):
        raise DesktopError("invalid update compatibility profile")
    paths = []
    for kind in ("settings", "documents"):
        if not isinstance(policy[kind], list):
            raise DesktopError("update paths must be lists")
        for value in policy[kind]:
            # Only one wildcard, for the Wine account name. Never accept hives,
            # program files, globbing of arbitrary trees or arbitrary host paths.
            parts = value.split("/") if isinstance(value, str) else []
            if (len(parts) < 4 or parts[:3] != ["drive_c", "users", "*"]
                    or any(p in {"", ".", ".."} or any(c in p for c in "*?[]\\:\0") for p in parts[3:])
                    or (kind == "settings" and (len(parts) < 6 or parts[3:5] not in
                        (["AppData", "Roaming"], ["AppData", "Local"])))
                    or (kind == "documents" and parts[3] not in {"Documents", "Desktop", "Pictures", "Music", "Videos"})):
                raise DesktopError("update paths must name qualified user settings or documents")
            folded = value.casefold()
            if any(folded == old or folded.startswith(old + "/") or old.startswith(folded + "/") for old in paths):
                raise DesktopError("overlapping update paths")
            paths.append(folded)
    return policy


def copy_file(source, destination):
    """Reflink where supported, with a bounded-memory ordinary copy fallback."""
    import fcntl
    info = Path(source).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o6000:
        raise DesktopError("state copies require ordinary files; source retained")
    try:
        with open(source, "rb") as src, open(destination, "xb") as dst:
            try:
                fcntl.ioctl(dst.fileno(), 0x40049409, src.fileno())  # FICLONE
            except OSError:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        shutil.copystat(source, destination)
        return destination
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise


def _real_path(root, relative):
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {".", ".."} for p in parts):
        raise DesktopError("unsafe generation path")
    path = Path(root)
    if path.is_symlink():
        raise DesktopError("linked state root")
    for part in parts:
        path /= part
        if path.is_symlink():
            raise DesktopError("linked generation or migration path; data retained")
    return path


def _migrate_paths(source, destination, patterns, *, replace_missing=False):
    users = _real_path(source, "drive_c/users")
    accounts = {p.name for p in users.iterdir()} if users.exists() else set()
    if replace_missing:
        target_users = _real_path(destination, "drive_c/users")
        if target_users.exists():
            accounts.update(p.name for p in target_users.iterdir())
    for name in accounts:
        account = users / name
        if account.is_symlink() or (account.exists() and not account.is_dir()):
            raise DesktopError("linked or invalid Wine user; migration refused")
        for pattern in patterns:
            relative = pattern.replace("/users/*/", "/users/" + account.name + "/", 1)
            src = _real_path(source, relative)
            if not src.exists():
                if replace_missing:
                    dst = _real_path(destination, relative)
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    elif dst.exists():
                        dst.unlink()
                continue
            # inspect before copying; no escaping, special or linked user data.
            # Even an in-tree link could alias settings to application binaries.
            members = [src, *src.rglob("*")] if src.is_dir() else [src]
            for member in members:
                mode = member.lstat().st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)) or mode & 0o6000:
                    raise DesktopError("migration requires ordinary files/directories; data retained")
            dst = _real_path(destination, relative)
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, copy_function=copy_file)
            else:
                copy_file(src, dst)


def _read_generations(root):
    path = _real_path(root, "state.json")
    if not path.is_file():
        return None
    value = json.loads(path.read_text())
    if value.get("schemaVersion") == "cage.desktop-generations/v1":
        import re
        for entry in value["generations"]:
            if entry["prefix"] != "prefix" and not re.fullmatch(r"generations/[a-f0-9]{32}", entry["prefix"]):
                raise DesktopError("invalid generation path")
            prefix = _real_path(root, entry["prefix"])
            marker = _real_path(prefix, ".cage-state.json")
            if (not (prefix / "drive_c").is_dir() or not marker.is_file()
                    or json.loads(marker.read_text()) != entry["identity"]):
                raise DesktopError("incomplete generation; data retained for recovery")
        _generation(value, value["active"])
        return value
    prefix = _real_path(root, "prefix")
    marker = _real_path(prefix, ".cage-state.json")
    if not (prefix / "drive_c").is_dir() or not marker.is_file() or json.loads(marker.read_text()) != value:
        raise DesktopError("incomplete legacy generation; data retained")
    return {"schemaVersion": "cage.desktop-generations/v1", "active": "prefix", "previous": None,
            "generations": [{"prefix": "prefix", "identity": value}]}


def _generation(record, name):
    matches = [entry for entry in record["generations"] if entry["prefix"] == name]
    if len(matches) != 1:
        raise DesktopError("missing or ambiguous state generation")
    return matches[0]


def state_info(root, identity):
    root = Path(root)
    record = _read_generations(root)
    known = {g["prefix"] for g in record["generations"]} if record else set()
    directory = _real_path(root, "generations")
    retained = [p.relative_to(root).as_posix() for p in directory.iterdir()
                if p.relative_to(root).as_posix() not in known] if directory.is_dir() else []
    return {"state": record, "packageIdentity": identity, "stateDirectory": str(root.absolute()),
            "retainedCandidates": sorted(retained)}


def prepare_generation(seed, inventory, root, identity, plan, action):
    """Called with the lifecycle lock held. Return prefix and pending commit.

    A pending generation is never the active one. Interrupted/failed candidates
    remain available for recovery, but are never automatically reused.
    """
    root = Path(root)
    record = _read_generations(root)
    policy = plan.get("desktop", {}).get("updates")
    if policy:
        validate_update_policy(policy)
    if record is None:
        if action == 'migrate':
            raise DesktopError('migration requires existing recorded legacy state; nothing imported')
        if action == "rollback":
            raise DesktopError("no previous generation to roll back")
        initialize_state(seed, inventory, root, identity)
        record = _read_generations(root)
    current = _generation(record, record["active"])
    if action == 'migrate' or (action == 'update' and current['identity'].get('schemaVersion') == 'cage.desktop-state/v0'
                              and identity.get('schemaVersion') == 'cage.desktop-state/v1'):
        if not policy:
            raise DesktopError('migration requires a qualified update policy; all state retained')
        migration_space(root, seed)
        snapshot_legacy(root, identity)
        action = 'update'
    if current["identity"] == identity and action != "rollback":
        if policy and identity.get("schemaVersion") == "cage.desktop-state/v1" and not current.get("profile"):
            current.update(profile=policy["profile"], application=plan.get("application", {}))
            _write_state_record(root / "state.json", record)
        return _real_path(root, current["prefix"]), None
    if action not in {"update", "rollback"}:
        raise DesktopError("different seed/runtime; close the app and use --cage-update, or restore the previous package and use --cage-rollback")
    if not policy:
        raise DesktopError("this recipe has no qualified update policy; all state retained")
    if current.get("profile", policy["profile"]) != policy["profile"]:
        raise DesktopError("incompatible update profiles; all state retained")
    if action == "rollback":
        if not record.get("previous"):
            raise DesktopError("no previous generation to roll back")
        original = _generation(record, record["previous"])
        legacy_match = (original["identity"].get("schemaVersion") == "cage.desktop-state/v0"
                        and all(original["identity"].get(key) == identity.get(key) for key in ("seedDigest", "runtimeDigest")))
        if original["identity"] != identity and not legacy_match:
            raise DesktopError("rollback requires the previous package/runtime; see --cage-state-info")
        source = _real_path(root, original["prefix"])
    else:
        if current["identity"].get("runtimeDigest") != identity.get("runtimeDigest"):
            raise DesktopError("runtime changes require separate migration qualification; all state retained")
        source = Path(seed)
        verify_inventory(source, inventory)
    import uuid
    parent = _real_path(root, "generations")
    parent.mkdir(mode=0o700, exist_ok=True)
    relative = "generations/" + uuid.uuid4().hex
    prefix = root / relative
    # Record preparation before any copy. A crash cannot make it active.
    _write_state_record(root / "transaction.json", {"status": "preparing", "action": action,
                        "candidate": relative, "previous": record["active"]})
    shutil.copytree(source, prefix, symlinks=True, copy_function=copy_file)
    if action == "update":
        verify_inventory(prefix, inventory)
        _migrate_paths(_real_path(root, current["prefix"]), prefix, policy["settings"])
    _migrate_paths(_real_path(root, current["prefix"]), prefix, policy["documents"], replace_missing=True)
    _write_state_record(prefix / ".cage-state.json", identity)
    # Check the application before it can write to the candidate.
    if not windows_path(prefix, plan["launch"]["entrypoint"]).is_file():
        raise DesktopError("updated application executable is missing; old generation retained")
    current.setdefault("profile", policy["profile"])
    record["previous"] = record["active"]
    record["active"] = relative
    record["generations"].append({"prefix": relative, "identity": identity,
        "profile": policy["profile"], "application": plan.get("application", {}),
        "action": action})
    return prefix, record


def commit_generation(root, record):
    # Prefix contents must reach disk before the active pointer. Wine has already
    # stopped. syncfs is not portable Python; fsync every regular file/directory.
    prefix = _real_path(root, record["active"])
    _flush_tree(prefix)
    descriptor = os.open(prefix.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _write_state_record(root / "state.json", record)
    try:
        _write_state_record(root / "transaction.json", {"status": "committed", "active": record["active"]})
    except OSError:
        pass  # state.json is the authoritative durable commit record.


@contextmanager
def lifecycle_lock(root):
    import fcntl
    root = Path(root)
    if root.is_symlink():
        raise DesktopError("application state directory cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(root / "launch.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DesktopError("this application is already running; close it before updating or launching") from exc
        try:
            yield descriptor
        finally:
            # Wine may pass inherited descriptors to detached Unix helpers. A
            # clean lifecycle must release the shared open-file-description lock
            # explicitly; SIGKILL still leaves the inherited crash guard held.
            fcntl.flock(lock, fcntl.LOCK_UN)


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
    identity = plan_identity(plan)
    seed = Path(plan["layout"]["seed"]) if plan["layout"].get("seed") else metadata_path.parent / "seed"
    if files == ['--cage-display-info']:
        with lifecycle_lock(state_root):
            print(json.dumps({'preference': display_preferences(state_root), 'hostDpi': host_dpi(),
                              'range': [96, 384], 'scope': 'X11/XWayland session; restart after scale changes'}))
        return 0
    if files[:1] == ['--cage-dpi']:
        if len(files) != 2 or not (files[1] in ('auto', 'preserve') or files[1].isdigit() and 96 <= int(files[1]) <= 384):
            raise DesktopError('--cage-dpi requires auto, preserve or an integer from 96 to 384')
        with lifecycle_lock(state_root):
            _write_state_record(state_root / 'display.json', {'dpi': int(files[1]) if files[1].isdigit() else files[1]})
            if files[1] == 'auto':
                record = _read_generations(state_root)
                if record:
                    prefix = _real_path(state_root, record['active'])
                    # Explicitly returning to auto adopts the current value,
                    # so a prior custom DPI does not immediately disable auto.
                    _write_state_record(prefix / '.cage-display.json', {'dpi': prefix_dpi(prefix)})
        return 0
    action = "launch"
    if files[:1] in (["--cage-update"], ["--cage-rollback"], ["--cage-migrate"]):
        action = files[0][7:]
        files = files[1:]
    elif files == ["--cage-state-info"]:
        with lifecycle_lock(state_root):
            print(json.dumps(state_info(state_root, identity), indent=2, sort_keys=True))
        return 0
    elif files and files[0].startswith("--cage-"):
        raise DesktopError("unknown Cage lifecycle option")
    if files[:1] == ["--"]:
        files = files[1:]
    with lifecycle_lock(state_root) as lock_fd:
        return _launch_locked(metadata_path, files, plan, inventory, state_root, identity, seed, action, lock_fd)


def _launch_locked(metadata_path, files, plan, inventory, state_root, identity, seed, action, lock_fd):
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
    environment.update(WINEARCH="win64")
    if plan.get('display') and plan.get('format') == 'flatpak':
        environment['FONTCONFIG_FILE'] = str(runtime_root / 'share/cage/fonts.conf')
        environment['FONTCONFIG_PATH'] = str(runtime_root / 'share/cage')
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
    assert_quiescent(state_root, server, environment)
    prefix, pending = prepare_generation(seed, inventory, state_root, identity, plan, action)
    environment["WINEPREFIX"] = str(prefix)
    configure_fonts(plan, prefix, wine, server, environment, state_root, lock_fd)
    configure_display(plan, state_root, prefix, wine, server, environment, lock_fd)
    # This maps the Flatpak namespace, not an unrestricted host filesystem.
    zdrive = prefix / "dosdevices/z:"
    if not zdrive.exists() and not zdrive.is_symlink():
        zdrive.symlink_to("/")
    arguments = document_arguments(files)
    contract = plan["launch"]
    executable = windows_path(prefix, contract["entrypoint"])
    if not executable.is_file():
        raise DesktopError("application executable is missing from persistent state")
    cwd = windows_path(prefix, contract["workingDirectory"]) if contract.get("workingDirectory") else executable.parent
    if not cwd.is_dir():
        raise DesktopError("application working directory is missing")
    result = _run_application([wine, contract["entrypoint"], *contract.get("args", []), *arguments],
                            server, environment, cwd, state_root, locked=True, lock_fd=lock_fd)

    if pending is not None and result == 0:
        commit_generation(state_root, pending)
    return result


def assert_quiescent(root, server, environment):
    """An orphan Wine service must not race migration after a killed launcher."""
    root = Path(root)
    prefixes = [_real_path(root, "prefix")]
    directory = _real_path(root, "generations")
    if directory.exists():
        prefixes.extend(_real_path(root, p.relative_to(root)) for p in directory.iterdir())
    for prefix in prefixes:
        if not prefix.is_dir():
            continue
        try:
            subprocess.run([server, "-w"], env={**environment, "WINEPREFIX": str(prefix)},
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1, check=True)
        except subprocess.TimeoutExpired as exc:
            raise DesktopError("Wine is still running in retained state; close it before updating or launching") from exc


def _run_application(command, server, environment, cwd, state_root, *, locked=False, lock_fd=None):
    """Own one prefix lifecycle; Wine services must not outlive its GUI app."""
    if not locked:
        with lifecycle_lock(state_root) as lock_fd:
            return _run_application(command, server, environment, cwd, state_root, locked=True, lock_fd=lock_fd)
    try:
        return subprocess.run(command, env=environment, cwd=cwd,
                              pass_fds=() if lock_fd is None else (lock_fd,)).returncode
    finally:
        subprocess.run([server, "-k"], env=environment, timeout=15, check=False)
        subprocess.run([server, "-w"], env=environment, timeout=30, check=True)


if __name__ == "__main__":
    try:
        raise SystemExit(launch(sys.argv[1], sys.argv[2:]))
    except (DesktopError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Cage desktop launch failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
