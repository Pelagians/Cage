"""Native exit repair preserves status-bearing code and immutable RPM aliases."""
from pathlib import Path
import hashlib
import json
import stat
from unittest.mock import patch

import pytest

from runtime import arm64ec
from runtime.desktop_launch import DesktopError

ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    vendor = tmp_path / 'vendor'; vendor.mkdir()
    original = b'ELF test note'.ljust(20, b'\0') + bytes.fromhex('f75bff97') + b'unchanged exit(status) call'
    output = original[:20] + bytes.fromhex('1f2003d5') + original[24:]
    record = json.loads((ROOT / 'runtime/vendor/wine-11.20-exit1/source.json').read_text())
    record['elf'].update(size=len(original), originalSha256=hashlib.sha256(original).hexdigest(),
                         sha256=hashlib.sha256(output).hexdigest(),
                         edits=[{'offset':20,'before':'f75bff97','after':'1f2003d5'}])
    source = vendor / 'source.json'; source.write_text(json.dumps(record))
    (vendor / 'NOTICE.txt').write_text('native exit fixture')
    target = arm64ec.runtime_target(); target['nativeExit']['sourceSha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    root = tmp_path / 'payload'; elf = root / record['elf']['path']; elf.parent.mkdir(parents=True)
    elf.write_bytes(original); elf.chmod(0o755)
    return vendor, target, root, elf, original, output


def test_native_exit_edit_is_atomic_and_preserves_alias_and_other_code(tmp_path):
    vendor,target,root,elf,original,output = fixture(tmp_path)
    alias = tmp_path / 'retained-original.so'; alias.hardlink_to(elf)
    with patch.object(arm64ec,'NATIVE_EXIT_VENDOR',vendor), patch.object(arm64ec,'runtime_target',return_value=target):
        arm64ec.install_native_exit_order(root)
    assert elf.read_bytes() == output and alias.read_bytes() == original
    assert elf.read_bytes()[24:] == b'unchanged exit(status) call'
    assert stat.S_IMODE(elf.stat().st_mode) == 0o755
    assert not elf.with_name(elf.name + '.cage-new').exists()
    assert (root/'share/licenses/cage-wine-11.20-exit1/source.json').read_bytes() == (vendor/'source.json').read_bytes()


@pytest.mark.parametrize('alteration', ['bytes','link','source','instruction','output'])
def test_native_exit_rejects_foreign_or_altered_inputs_without_writes(tmp_path, alteration):
    vendor,target,root,elf,original,output = fixture(tmp_path)
    if alteration == 'bytes':elf.write_bytes(b'foreign')
    if alteration == 'link':
        backing = tmp_path/'backing'; elf.rename(backing); elf.symlink_to(backing)
    if alteration == 'source':target['nativeExit']['sourceSha256'] = '0'*64
    if alteration in ('instruction','output'):
        source = vendor/'source.json'; record = json.loads(source.read_text())
        if alteration == 'instruction':record['elf']['edits'][0]['before'] = '00000000'
        else:record['elf']['sha256'] = '0'*64
        source.write_text(json.dumps(record)); target['nativeExit']['sourceSha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    before = elf.read_bytes()
    with patch.object(arm64ec,'NATIVE_EXIT_VENDOR',vendor), patch.object(arm64ec,'runtime_target',return_value=target), pytest.raises(DesktopError):
        arm64ec.install_native_exit_order(root)
    assert elf.read_bytes() == before
    assert not (root/'share/licenses/cage-wine-11.20-exit1').exists()


def test_guarded_original_identity_remains_an_explicit_immutable_target():
    previous = json.loads((ROOT/'runtime/legacy/wine-arm64ec-11.20-fex-2610-cage1.json').read_text())
    assert arm64ec.existing_runtime_target(previous) == previous
    assert previous['id'] != arm64ec.runtime_target()['id']
    assert 'nativeExit' not in previous
    assert previous['translation'] == arm64ec.runtime_target()['translation']
    with pytest.raises(DesktopError):arm64ec.existing_runtime_target(previous | {'nativeExit':arm64ec.runtime_target()['nativeExit']})


def test_native_exit_preserves_a_preexisting_staging_file(tmp_path):
    vendor,target,root,elf,original,_ = fixture(tmp_path)
    staging = elf.with_name(elf.name + '.cage-new'); staging.write_bytes(b'retained staging data')
    with patch.object(arm64ec,'NATIVE_EXIT_VENDOR',vendor), patch.object(arm64ec,'runtime_target',return_value=target), pytest.raises(FileExistsError):
        arm64ec.install_native_exit_order(root)
    assert elf.read_bytes() == original and staging.read_bytes() == b'retained staging data'
