#!/usr/bin/env python3
"""Apply shared assertions to native Linux/Windows probe observations.

Input directory: host.json and FORMAT.linux.json / FORMAT.windows.json for each
format. Missing controls, unavailable hardware and unrun probes are blocked.
This report covers runtime observations; application workflows remain separate.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.capabilities import compile_capabilities
from core.manifest import load_manifest


def evaluate(plan,linux,windows,host):
    def case(checks):
        if not checks or any(actual is None for actual,expected in checks):return {'status':'blocked','evidence':['missing observation or independent host control']}
        return {'status':'passed' if all(actual==expected for actual,expected in checks) else 'failed','evidence':['shared Linux and Windows probe assertions']}
    baseline=linux.get('baseline',{});fs=linux.get('filesystem',{});winfs=windows.get('filesystem',{});control=host.get('controls',{})
    grant=any(x['grant'] and x['grant']['kind']=='network' for x in plan['requests'])
    devices=any(x['grant'] and (x['grant'].get('class')=='all' or x['fallback']) for x in plan['requests'])
    files=[x['grant'] for x in plan['requests'] if x['grant'] and x['grant']['kind']=='filesystem']
    writable=any(x['access']=='read-write' for x in files)
    read_only=any(x['access']=='read-only' for x in files)
    cases={
      'baseline':case([(baseline.get('noNewPrivileges'),True),(baseline.get('zeroCapabilities'),True),(baseline.get('seccomp'),True),
                       (fs.get('packageMutation'),False),(fs.get('runtimeMutation'),False),(fs.get('protectedRead'),False),
                       (control.get('protectedRead'),True)]),
      'filesystem':case([(fs.get('read'),bool(files)),(fs.get('readScopeMutation'),writable and not read_only),(fs.get('write'),writable),(fs.get('siblingRead'),False),
                         (winfs.get('read'),bool(files)),(winfs.get('write'),writable),(winfs.get('siblingRead'),False),
                         (winfs.get('protectedRead'),False),(control.get('siblingRead'),True),(control.get('read'),True),(control.get('write'),True)]),
      'network':case([(linux.get('network',{}).get('tcp'),grant),(linux.get('network',{}).get('abstract'),grant),
                      (windows.get('network',{}).get('tcp'),grant),(control.get('tcp'),True),(control.get('abstract'),True)])}
    if devices:
        cases['devices']=case([(linux.get('devices',{}).get('initialAccessible'),True),(control.get('deviceAccessible'),True),
                                (windows.get('devices',{}).get('controlledDeviceDetected'),True)])
    if devices and any(x['grant'] and x['resolved'].get('hotplug')=='required' for x in plan['requests']):
        cases['hotplug']=case([(linux.get('devices',{}).get('liveTransitionObserved'),True),
                               (windows.get('devices',{}).get('controlledReconnectObserved'),True),(control.get('dedicatedRecoverableHardware'),True)])
    return cases


def read(path):
    if not path.exists():return {}
    if path.stat().st_size>4*1024**2:raise ValueError('probe report exceeds limit')
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('probe report must be an object')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe',type=Path);parser.add_argument('directory',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();recipe=load_manifest(args.recipe);host=read(args.directory/'host.json')
    formats={}
    for kind in ('oci','flatpak','appimage'):
        plan=compile_capabilities(recipe,kind)
        cases=evaluate(plan,read(args.directory/(kind+'.linux.json')),read(args.directory/(kind+'.windows.json')),host)
        formats[kind]={'contractDigest':plan['contractDigest'],'cases':cases}
    statuses=[case['status'] for target in formats.values() for case in target['cases'].values()]
    result={'schemaVersion':'cage.capability-parity-observations/v1','status':'failed' if 'failed' in statuses else 'blocked' if 'blocked' in statuses else 'passed',
            'formats':formats,'applicationWorkflow':'not-qualified-by-this-report','host':host.get('host',{})}
    data=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if args.output:args.output.write_text(data)
    print(data,end='')
    return 1 if result['status']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
