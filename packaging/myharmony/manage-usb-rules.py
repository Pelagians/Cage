#!/usr/bin/env python3
"""Explicit administrative Harmony uaccess setup with shared ownership receipts."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path,data,mode=0o600):
    fd,name=tempfile.mkstemp(prefix='.cage-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(data);output.flush();os.fsync(output.fileno())
        os.chmod(name,mode);os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:Path(name).unlink(missing_ok=True)


def apply(root,rules,owner,*,remove=False):
    root,rules=Path(root),Path(rules)
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{2,180}',owner):raise ValueError('invalid application owner ID')
    directory=root/'etc/cage/udev-rules';target=root/'etc/udev/rules.d/70-cage-myharmony.rules'
    for path in (directory,target.parent):
        if any(p.is_symlink() for p in (path,*path.parents) if p!=root.parent):raise ValueError('linked rules/state path retained')
        path.mkdir(parents=True,exist_ok=True,mode=0o700 if path==directory else 0o755)
        info=path.stat()
        if info.st_uid!=os.geteuid() or info.st_mode & 0o022:raise ValueError('rules/state directory is not exclusively administrator controlled')
    directory.chmod(0o700)
    receipt=directory/'myharmony.json'
    if receipt.is_symlink() or target.is_symlink():raise ValueError('linked rules/receipt retained')
    for path in (receipt,target):
        if path.exists() and (not stat.S_ISREG(path.stat().st_mode) or path.stat().st_uid!=os.geteuid()):
            raise ValueError('unowned or non-regular rules/receipt retained')
    with (directory/'lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        record=json.loads(receipt.read_text()) if receipt.exists() else None
        if record and record.get('schemaVersion')!='cage.host-udev-ownership/v1':raise ValueError('unknown ownership receipt retained')
        if record and target.exists() and sha(target)!=record['sha256']:
            raise ValueError('administrator-modified rules retained; reconcile the file explicitly')
        changed=False
        if remove:
            if not record or owner not in record['owners']:return {'changed':False,'owners':record['owners'] if record else []}
            record['owners'].remove(owner)
            if not record['owners'] and record['createdByCage'] and target.exists():
                backup=directory/(record['sha256']+'.rules')
                if not backup.exists():atomic(backup,target.read_bytes())
                target.unlink();changed=True
        else:
            if rules.is_symlink() or not rules.is_file():raise ValueError('rules source must be a regular file')
            current=sha(rules)
            if record is None:
                if target.exists() and sha(target)!=current:raise ValueError('existing untracked rules retained; no file overwritten')
                record={'schemaVersion':'cage.host-udev-ownership/v1','sha256':current,'owners':[],'createdByCage':not target.exists()}
            if target.exists() and record['sha256']!=current:
                backup=directory/(record['sha256']+'.rules')
                if not backup.exists():atomic(backup,target.read_bytes())
            if not target.exists() or sha(target)!=current:
                atomic(target,rules.read_bytes(),0o644);changed=True
            record['sha256']=current
            if owner not in record['owners']:record['owners'].append(owner)
            record['owners'].sort()
        atomic(receipt,(json.dumps(record,sort_keys=True,indent=2)+'\n').encode())
        return {'changed':changed,'owners':record['owners'],'rulesRetained':target.exists(),'recoveryDirectory':str(directory)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','remove'],nargs='?',default='install')
    parser.add_argument('--owner',default='io.github.Pelagians.Cage.MyHarmony')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('run this administrative helper with sudo; launch MyHarmony as your regular user')
    result=apply('/',Path(__file__).with_name('70-cage-myharmony.rules'),args.owner,remove=args.action=='remove')
    if result['changed']:subprocess.run(['udevadm','control','--reload-rules'],check=True)
    print(json.dumps(result,indent=2))
    print('Reconnect the remote/hub. Host authorization and sandbox device permission are separate.')


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError) as exc:raise SystemExit(str(exc))
