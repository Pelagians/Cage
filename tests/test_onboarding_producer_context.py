"""Cold reproduction refuses existing stores rather than cleaning them."""
from pathlib import Path
import importlib.util

import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/record-onboarding-producer.py'
spec=importlib.util.spec_from_file_location('producer_context',SCRIPT)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@pytest.mark.parametrize('linked',[False,True])
def test_cold_mode_preserves_and_refuses_existing_store(tmp_path,linked):
    retained=tmp_path/'retained';retained.mkdir();(retained/'recovery').write_bytes(b'original recovery')
    store=tmp_path/'store'
    if linked:store.symlink_to(retained,target_is_directory=True)
    else:store=retained
    with pytest.raises(ValueError):module.context(store,cold=True,cache_hit='')
    assert (retained/'recovery').read_bytes()==b'original recovery'
    assert store.exists()


def test_cold_mode_requires_skipped_restore_without_creating_store(tmp_path):
    store=tmp_path/'new'
    for hit in ('true','false'):
        with pytest.raises(ValueError):module.context(store,cold=True,cache_hit=hit)
    data=module.context(store,cold=True,cache_hit='')
    assert data['producerCache']=={'store':str(store),'coldRequested':True,'restoreSkipped':True,
                                   'primaryCacheHit':False,'storePresentBeforeBuild':False}
    assert not store.exists()


def test_warm_control_records_existing_store_without_mutation(tmp_path):
    store=tmp_path/'warm';store.mkdir();saved=store/'retained';saved.write_bytes(b'cache')
    data=module.context(store,cold=False,cache_hit='true')
    assert data['producerCache']['primaryCacheHit'] is True
    assert data['producerCache']['storePresentBeforeBuild'] is True
    assert saved.read_bytes()==b'cache'
