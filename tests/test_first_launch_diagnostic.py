"""Fresh-install diagnostics cannot reuse state or become release qualification."""
from pathlib import Path
import hashlib
import importlib.util
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from artifact import releases

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('override,extra',[
    ({'GITHUB_ACTIONS':'false'},[]),
    ({'CAGE_TEST_DISCARD_PREFIXES':'0'},[]),
    ({},['--runtime-migration']),
    ({},['--legacy','unused']),
    ({'CAGE_TEST_INITIAL_RELAUNCHES':'1'},[]),
])
def test_first_launch_mode_refuses_nonprivate_or_warm_trials(tmp_path,override,extra):
    env=dict(os.environ,GITHUB_ACTIONS='true',CAGE_TEST_DISCARD_PREFIXES='1',
             CAGE_TEST_INITIAL_RELAUNCHES='0',CAGE_TEST_EVIDENCE=str(tmp_path/'must-not-be-created'))
    env.update(override)
    result=subprocess.run([sys.executable,str(ROOT/'scripts/test-onboarding-poc.py'),
        'appimage','absent-baseline','absent-candidate','--trusted','--qualification','absent-evidence',
        '--first-launch-only',*extra],env=env,capture_output=True,text=True)
    assert result.returncode==2 and 'Traceback' not in result.stderr
    assert not (tmp_path/'must-not-be-created').exists()


def test_first_launch_observation_cannot_qualify_release():
    with pytest.raises(releases.ReleaseError,match='successful application qualification'):
        releases.verify_evidence({'format':'appimage','architecture':'aarch64'},
            {'schemaVersion':'cage.appimage-first-launch-diagnostic/v1',
             'status':'observed','diagnosticOnly':True,'freshInstall':True,
             'exitCode':0,'wineStopped':True,'documentsPreserved':True})


@pytest.mark.parametrize('invalid',['none','signature','payload','symlink'])
def test_diagnostic_retirement_preserves_sources_recovery_and_metadata(tmp_path,monkeypatch,invalid):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    spec=importlib.util.spec_from_file_location('first_launch_proof',ROOT/'scripts/test-onboarding-poc.py')
    proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
    cache=tmp_path/'private-cache';folder=cache/'releases/one';folder.mkdir(parents=True)
    source=tmp_path/'original.AppImage';source.write_bytes(b'original producer')
    manifest=folder/'release.json';manifest.write_bytes(b'signed manifest')
    signature=folder/'release.json.sig';signature.write_bytes(b'signature')
    recovery=folder/'retained-recovery.AppImage';recovery.write_bytes(b'other retained bytes')
    payload=folder/'app.AppImage'
    if invalid=='symlink':payload.symlink_to(source)
    else:payload.write_bytes(b'consumed copy' if invalid!='payload' else b'changed')
    entry={'package':{'name':payload.name,'size':len(b'consumed copy'),
                      'sha256':hashlib.sha256(b'consumed copy').hexdigest()}}
    def verify(*args):
        if invalid=='signature':raise releases.ReleaseError('bad signature')
        return {'artifacts':[entry]}
    with patch.object(releases,'verify_manifest',side_effect=verify):
        if invalid!='none':
            with pytest.raises((releases.ReleaseError,AssertionError)):
                proof.retire_first_launch_payloads(cache,tmp_path/'public.pem')
            assert payload.exists()
        else:
            proof.retire_first_launch_payloads(cache,tmp_path/'public.pem')
            assert not payload.exists()
    assert source.read_bytes()==b'original producer'
    assert recovery.read_bytes()==b'other retained bytes'
    assert manifest.read_bytes()==b'signed manifest' and signature.read_bytes()==b'signature'
