#!/usr/bin/env python3
"""Record the cache boundary before a disposable onboarding producer build."""
from pathlib import Path
import argparse
import json
import os


def context(store, *, cold, cache_hit):
    store=Path(store)
    if store.is_symlink():raise ValueError('producer store must not be a symlink')
    present=store.exists()
    if cold and (present or cache_hit):
        raise ValueError('cold producer requires a new store and skipped restore; existing data was not removed')
    if cache_hit not in ('','true','false'):raise ValueError('invalid cache result')
    cpu={}
    for line in Path('/proc/cpuinfo').read_text().splitlines():
        key,separator,value=line.partition(':');key=key.strip()
        if separator and key in ('model name','Features','CPU implementer','CPU part'):
            cpu.setdefault(key,set()).add(value.strip())
    return {'schemaVersion':'cage.onboarding-producer-context/v1',
        'sourceRevision':os.environ.get('CAGE_TEST_SOURCE_REVISION'),
        'architecture':os.uname().machine,'kernel':os.uname().release,'pageSize':os.sysconf('SC_PAGE_SIZE'),
        'runnerImageVersion':os.environ.get('ImageVersion'),
        'cpu':{key:sorted(values) for key,values in cpu.items()},
        'producerCache':{'store':str(store),'coldRequested':cold,'restoreSkipped':cold,
                         'primaryCacheHit':cache_hit=='true','storePresentBeforeBuild':present},
        'physicalUsbSynchronization':'unqualified'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cold',action='store_true');p.add_argument('--cache-hit',default='')
    a=p.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true':p.error('producer context is a disposable CI diagnostic')
    data=context(a.store,cold=a.cold,cache_hit=a.cache_hit)
    with a.output.open('x') as output:output.write(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':main()
