#!/usr/bin/env python3
"""Verify the real failure-only observer on a disposable native process, not Wine qualification."""
from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

# Run in the same unprivileged consumer shape as the real proof. The deliberate
# short deadline and exit73 are exclusive to this component fixture.
CONSUMER = r'''
from pathlib import Path
import importlib.util, os, subprocess, sys
sys.path.insert(0, str(Path(sys.argv[1])/'scripts'))
spec=importlib.util.spec_from_file_location('proof',Path(sys.argv[1])/'scripts/test-onboarding-poc.py')
proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
target=subprocess.Popen(['/usr/bin/sleep','300'])
try:
    try:target.wait(timeout=.1)
    except subprocess.TimeoutExpired:
        proof.shutdown_diagnostics(target,Path(sys.argv[2])/'controlled-shutdown','sleep')
    else:raise RuntimeError('controlled stall unexpectedly returned')
finally:
    target.terminate();target.wait(timeout=10)
raise SystemExit(73)
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true':p.error('native observer component requires disposable CI')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    rows=[]
    for mode in ('normal','failure'):
        evidence=output/mode;evidence.mkdir();cidfile=evidence/'container.cid'
        command=[sys.executable,str(ROOT/'scripts/observe-appimage-proof.py'),
            '--cidfile',str(cidfile),'--evidence',str(evidence),'--',
            'podman','run','--cidfile',str(cidfile),'--rm','--net=none','--userns=keep-id',
            '--user',str(os.getuid())+':'+str(os.getgid()),
            '-v',str(ROOT)+':'+str(ROOT)+':ro','-v',str(output)+':'+str(output),
            '-w',str(ROOT),'-e','GITHUB_ACTIONS','-e','PYTHONDONTWRITEBYTECODE=1',
            '-e','CAGE_TEST_HOST_DIAGNOSTICS=1',args.image,'python3','-c',
            CONSUMER if mode=='failure' else 'raise SystemExit(0)',str(ROOT),str(evidence)]
        try:child=subprocess.run(command,timeout=180,check=False)
        finally:
            if cidfile.is_file():
                container=cidfile.read_text().strip()
                if re.fullmatch('[a-f0-9]{64}',container):
                    subprocess.run(['podman','rm','--force',container],capture_output=True,timeout=15,check=False)
        assert child.returncode==(73 if mode=='failure' else 0), 'observer altered fixture outcome'
        requests=list(evidence.glob('*-host-request.json'))
        if mode=='normal':
            assert not requests and not list(evidence.glob('*.log')), 'normal process was inspected'
        else:
            assert len(requests)==1 and not list(evidence.glob('*.error.log'))
            assert requests[0].with_suffix('.done').is_file()
            logs=list(evidence.glob('controlled-shutdown-host-request-*-*.log'))
            stacks=[path for path in logs if re.search(r'(?m)^#0\s',path.read_text())]
            assert stacks, 'no real native stack captured; fixture remains failed'
            assert all('ptrace: Operation not permitted' not in path.read_text() for path in stacks)
        rows.append({'case':mode,'childExitCode':child.returncode,'requests':len(requests)})
    (output/'observer-component.json').write_text(json.dumps({
        'schemaVersion':'cage.failure-observer-component/v1','status':'passed','diagnosticOnly':True,
        'architecture':os.uname().machine,'cases':rows,'applicationQualification':False,
        'kernel':os.uname().release,'pageSize':os.sysconf('SC_PAGE_SIZE'),
        'consumerImage':subprocess.check_output(['podman','image','inspect',args.image,'--format','{{.Id}}'],text=True).strip(),
        'gdb':subprocess.check_output(['gdb','--version'],text=True).splitlines()[0],
        'apparmorEnabled':Path('/sys/module/apparmor/parameters/enabled').read_text().strip(),
        'usernsRestriction':Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns').read_text().strip(),
        'wineArm64ecUnwinding':'requires an actual Wine failure capture',
        'physicalUsbSynchronization':'unqualified'},indent=2)+'\n')
    print('Native failure-only observer verified; controlled child still exited73.',flush=True)


if __name__=='__main__':main()
