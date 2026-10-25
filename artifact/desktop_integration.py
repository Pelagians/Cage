"""Managed host desktop entry, owned through the canonical authority receipt."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from artifact import authority, releases as r
from runtime.desktop_launch import lifecycle_lock, _write_state_record, desktop_entry
from runtime.appimage_launch import desktop_quote, refresh_desktop_cache


def install(release, root):
    app=release['manifest']['application']['id'];kind=release['entry']['format']
    executable=shutil.which('cage')
    if not executable:return {'status':'host-setup-required','reason':'Install host Cage to register its desktop launcher; module CLI launches remain available.'}
    executable=str(Path(executable).absolute())
    folder=authority.authority_folder(app)
    key=folder/'publisher.pem'
    if any(any(ord(c)<32 for c in str(value)) for value in (executable,root,key)):
        raise r.ReleaseError('host launcher paths contain unsupported control characters')
    data=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))
    target=data/'applications'/(app+'.desktop')
    with lifecycle_lock(folder):
        owner=authority.read_authority(app)
        if not owner or kind not in owner['formats']:raise r.ReleaseError('desktop integration requires canonical authority')
        previous=owner.get('desktopEntry')
        if previous and previous['format']!=kind:
            return {'status':'retained','defaultFormat':previous['format'],'path':previous['path']}
        if target.exists() or target.is_symlink():
            if not previous or target.is_symlink() or r.hash_file(r.regular(target))!=previous['sha256']:
                return {'status':'conflict','reason':'Existing or modified desktop entry retained; use cage release run.','path':str(target)}
        command='/usr/bin/env '+desktop_quote(executable)+' release run '+desktop_quote(app)+' --format '+kind
        command+=' --key '+desktop_quote(key)+' --cache-dir '+desktop_quote(root)+' -- %F'
        content=desktop_entry(release['entry']['plan'],command).encode()
        target.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.cage-desktop-',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as output:output.write(content);output.flush();os.fsync(output.fileno())
            os.chmod(name,0o644);os.replace(name,target)
        finally:Path(name).unlink(missing_ok=True)
        owner['desktopEntry']={'format':kind,'path':str(target),'sha256':hashlib.sha256(content).hexdigest()}
        _write_state_record(folder/'authority.json',owner)
    refresh_desktop_cache(target.parent)
    return {'status':'installed','path':str(target),'defaultFormat':kind}
