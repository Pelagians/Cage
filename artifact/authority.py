"""Canonical app-ID authority pins in the existing release ledger.

Only installation provenance is kept here. Native permissions remain native;
artifact cache locations cannot create an independent trust namespace.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from artifact import releases as r
from runtime.desktop_launch import lifecycle_lock, _write_state_record


def authority_folder(app):
    if not isinstance(app, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{2,180}', app):
        raise r.ReleaseError('invalid authority application ID')
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))
    return data / 'cage/releases/installed' / app


def read_authority(app):
    folder = authority_folder(app)
    path = folder/'authority.json'
    if folder.is_symlink() or path.is_symlink():
        raise r.ReleaseError('linked application authority; all data retained')
    if not path.exists(): return None
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise r.ReleaseError('application authority is not exclusively user controlled')
    value = r.parse(r.small(r.regular(path)))
    if (value.get('schemaVersion') != 'cage.release-authority/v1' or value.get('applicationId') != app
            or not re.fullmatch('[a-f0-9]{64}', value.get('publisherKeySha256', ''))
            or not isinstance(value.get('formats'), dict)):
        raise r.ReleaseError('invalid application authority; all data retained')
    return value


def flatpak_refs(app):
    """Native CLI metadata only; never execute application code for inspection."""
    found = []
    try:
        result = subprocess.run(['flatpak', 'list', '--app', '--columns=ref,origin,installation'],
                                check=True, capture_output=True, text=True)
    except FileNotFoundError:
        return []
    except subprocess.CalledProcessError as exc:
        raise r.ReleaseError('cannot inspect native Flatpak installation identities') from exc
    for line in result.stdout.splitlines():
        columns = line.split('\t')
        ref = columns[0].strip()
        if ref.startswith('app/'): ref = ref[4:]
        if ref.split('/')[0] == app:
            found.append({'ref': ref, 'origin': columns[1] if len(columns)>1 else '',
                          'installation': columns[2] if len(columns)>2 else ''})
    return found


def flatpak_user_directory():
    data=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))
    return Path(os.environ.get('FLATPAK_USER_DIR',str(data/'flatpak'))).resolve()


def claim(app, key, kind, ledger_root, *, native_ref=None, adopt=False, occupied=False):
    if kind not in r.FORMATS: raise r.ReleaseError('unknown authority format')
    _, fingerprint = r.public_key(key)
    root = Path(ledger_root).resolve()
    folder = r.directory(authority_folder(app))
    with lifecycle_lock(folder):
        record = read_authority(app)
        if record and record['publisherKeySha256'] != fingerprint:
            raise r.ReleaseError('app ID belongs to a different publisher; use a fresh application ID')
        # Existing format ledgers predate the canonical pin. Do not let a new
        # format or cache establish a contradictory authority over their ID.
        roots={root,folder.parent.parent}
        roots.update(Path(value['ledgerRoot']) for value in (record or {}).get('formats',{}).values())
        for known_root in roots:
            for known_format in r.FORMATS:
                ledger=known_root/'installed'/app/known_format/'installation.json'
                if ledger.exists() or ledger.is_symlink():
                    installed=r.parse(r.small(r.regular(ledger)))
                    if installed.get('publisherKeySha256')!=fingerprint:
                        raise r.ReleaseError('existing format ledger belongs to a different publisher; use a fresh application ID')
        old = (record or {}).get('formats', {}).get(kind)
        if old and old['ledgerRoot'] != str(root):
            raise r.ReleaseError('application format is registered in another cache; use its existing ledger root')
        native_installation=str(flatpak_user_directory()) if kind=='flatpak' else None
        if old and kind=='flatpak' and old.get('nativeInstallation')!=native_installation:
            raise r.ReleaseError('app ID is registered in another native Flatpak installation; retain it and use a fresh ID')
        refs = flatpak_refs(app) if kind == 'flatpak' else []
        if len(refs)>1 or (refs and (refs[0]['installation'] != 'user' or native_ref and refs[0]['ref'] != native_ref)):
            raise r.ReleaseError('another Flatpak ref/installation shares this app ID; retain it and use a fresh ID')
        if not old and (occupied or refs) and not adopt:
            raise r.ReleaseError('untracked native installation/data; explicit verified adoption required')
        if record is None:
            record = {'schemaVersion':'cage.release-authority/v1','applicationId':app,
                      'publisherKeySha256':fingerprint,'formats':{}}
        # Adoption's exact package/state proof is performed before this call.
        record['formats'][kind] = {'ledgerRoot':str(root), 'nativeRef':native_ref,'nativeInstallation':native_installation}
        pem = r.small(key, 64*1024)
        if (folder/'publisher.pem').exists():
            if r.public_key(folder/'publisher.pem')[1] != fingerprint:
                raise r.ReleaseError('canonical publisher public key changed')
        else:
            fd = os.open(folder/'publisher.pem', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as output: output.write(pem)
        _write_state_record(folder/'authority.json', record)
        return record


def registered(app, kind):
    record = read_authority(app)
    if not record or kind not in record['formats']:
        raise r.ReleaseError('no canonical managed installation for this app/format')
    entry = record['formats'][kind]
    if kind=='flatpak' and entry.get('nativeInstallation')!=str(flatpak_user_directory()):
        raise r.ReleaseError('native Flatpak installation differs from canonical app-ID authority')
    return record, Path(entry['ledgerRoot']), authority_folder(app)/'publisher.pem'
