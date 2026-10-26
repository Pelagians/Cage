#!/usr/bin/env python3
"""Shared Linux observations. Run inside each adapter against disposable fixtures.

This emits observations, never an application/hardware qualification pass. Host
controls must independently prove the canaries/endpoints exist and are allowed.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
import time
import tempfile
import subprocess
import sys
import traceback


def readable(path):
    try:
        with Path(path).open('rb') as source:return source.read(64)==b'cage-probe-canary\n'
    except OSError:return False


def private_runtime_directory(path):
    if not path:return False
    try:
        info=Path(path).lstat()
        return stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode)==0o700 and info.st_uid==os.getuid()
    except OSError:return False


def writable(directory):
    owned=[]
    try:
        fd,name=tempfile.mkstemp(prefix='cage-parity-',suffix='.tmp',dir=directory)
        owned.append(Path(name))
        with os.fdopen(fd,'wb') as output:
            output.write(b'cage-parity-write\n');output.flush();os.fsync(output.fileno())
        other=Path(name+'.renamed')
        with other.open('xb'):pass
        owned.append(other)
        Path(name).replace(other)
        return other.read_bytes()==b'cage-parity-write\n'
    except OSError:return False
    finally:
        for path in owned:
            try:path.unlink(missing_ok=True)
            except OSError:pass


def connect(address,family=socket.AF_INET):
    try:
        with socket.socket(family,socket.SOCK_STREAM) as client:
            client.settimeout(2);client.connect(address);client.sendall(b'cage-parity-ping\n')
            return client.recv(64)==b'cage-parity-pong\n'
    except OSError:return False


def safe_device(path):
    try:
        info=Path(path).stat()
        if not stat.S_ISCHR(info.st_mode) or (os.major(info.st_rdev),os.minor(info.st_rdev))!=(1,3):return False
        fd=os.open(path,os.O_WRONLY|os.O_NONBLOCK)
        try:return os.write(fd,b'')==0
        finally:os.close(fd)
    except OSError:return False


def readonly_mount(path):
    if not path or not Path(path).is_dir():return None
    return bool(os.statvfs(path).f_flag & os.ST_RDONLY)


def emit(path,value):
    path=Path(path)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as output:
        json.dump(value,output,sort_keys=True);output.write('\n');output.flush();os.fsync(output.fileno())
        temporary=Path(output.name)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def observe(args):
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    result={'schemaVersion':'cage.capability-probe/v1','status':'observed','qualification':'not-an-application-or-hardware-pass',
            'baseline':{'noNewPrivileges':status.get('NoNewPrivs','').strip()=='1',
                        'zeroCapabilities':int(status.get('CapEff','1').strip(),16)==0,'seccomp':status.get('Seccomp','').strip()=='2'},
            'filesystem':{'read':readable(args.read),'readScopeMutation':writable(Path(args.read).parent),
                          'write':writable(args.write),'packageMutation':writable(args.package) if args.package else None,
                          'runtimeMutation':writable(args.runtime) if args.runtime else None,'siblingRead':readable(args.denied),'protectedRead':readable(args.protected)},
            'network':{'tcp':connect(('127.0.0.1',args.port)) if args.port else None,
                       'abstract':connect('\0'+args.abstract,socket.AF_UNIX) if args.abstract else None}}
    result['mounts']={'packageReadOnly':readonly_mount(args.package),'runtimeReadOnly':readonly_mount(args.runtime)}
    result['display']={'x11EnvironmentPresent':bool(os.environ.get('DISPLAY')),
                       'waylandEnvironmentPresent':bool(os.environ.get('WAYLAND_DISPLAY')),
                       'x11SocketsVisible':bool(list(Path('/tmp/.X11-unix').glob('X*')))}
    if os.environ.get('WAYLAND_DISPLAY'):
        result['display']['privateRuntimeDirectory']=private_runtime_directory(os.environ.get('XDG_RUNTIME_DIR',''))
    if getattr(args,'old',None):result['filesystem']['previousRead']=readable(args.old)
    if getattr(args,'shm',None):result['baseline']['hostSharedMemoryVisible']=readable(args.shm)
    if getattr(args,'host_process_pid',None):
        try:visible=args.host_process_marker.encode() in Path(f'/proc/{args.host_process_pid}/cmdline').read_bytes()
        except OSError:visible=False
        result['baseline']['hostProcessVisible']=visible
    if getattr(args,'wine',None):
        version=subprocess.run([args.wine,'--version'],capture_output=True,text=True,check=True,timeout=15)
        result['runtime']={'wine':version.stdout.strip(),'python':sys.version.split()[0],
                           'executable':os.readlink('/proc/self/exe')}
    if args.device:
        if not str(args.device).startswith('/dev/cage-parity-'):raise ValueError('use a dedicated /dev/cage-parity-* null fixture')
        initial=safe_device(args.device)
        if getattr(args,'ready',None):emit(args.ready,{'initialDeviceAccessible':initial})
        if not getattr(args,'output',None):
            print(json.dumps({'event':'hotplug-ready','initialDeviceAccessible':initial}),flush=True)
        end=time.monotonic()+args.hotplug_seconds
        changed=False;reconnected=False
        while time.monotonic()<end:
            accessible=safe_device(args.device)
            if accessible!=initial:changed=True
            if changed and accessible==initial:reconnected=True;break
            time.sleep(.1)
        result['devices']={'initialAccessible':initial,'liveTransitionObserved':changed,
                           'reconnectObserved':reconnected,
                           'sysfsUsbPresent':Path('/sys/bus/usb/devices').is_dir(),'udevDataPresent':Path('/run/udev/data').is_dir()}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read',required=True);parser.add_argument('--write',required=True)
    parser.add_argument('--denied',required=True);parser.add_argument('--protected',required=True)
    parser.add_argument('--package');parser.add_argument('--runtime')
    parser.add_argument('--port',type=int);parser.add_argument('--abstract')
    parser.add_argument('--device');parser.add_argument('--hotplug-seconds',type=float,default=15)
    parser.add_argument('--old');parser.add_argument('--shm');parser.add_argument('--wine')
    parser.add_argument('--host-process-pid',type=int);parser.add_argument('--host-process-marker')
    parser.add_argument('--ready');parser.add_argument('--output')
    args=parser.parse_args()
    try:result=observe(args)
    except Exception:
        if args.output:emit(args.output,{'status':'failed','error':traceback.format_exc()})
        raise
    if args.output:emit(args.output,result)
    else:print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
