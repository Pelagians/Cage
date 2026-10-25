import copy
import json
from pathlib import Path
import tempfile
import unittest

from core.capabilities import CapabilityError, compile_capabilities, flatpak_permissions, normalize
from core.manifest import Manifest, ManifestError, load_manifest

ROOT = Path(__file__).resolve().parents[1]


def recipe():
    return load_manifest(ROOT / 'docs/proposals/capability-parity/examples/myharmony-compat.cage.yaml').to_dict()


class CapabilityContractTests(unittest.TestCase):
    def test_v0_roundtrip_and_v1_canonical_identity(self):
        old = load_manifest(ROOT / 'recipes/myharmony.cage.yaml')
        self.assertEqual(Manifest.from_dict(old.to_dict()).to_dict(), old.to_dict())
        raw = recipe()
        parsed = Manifest.from_dict(raw)
        self.assertNotIn('network', parsed.to_dict()['runtime'])
        self.assertEqual(parsed.runtime.network, 'host')
        self.assertEqual(parsed.to_dict(), Manifest.from_dict(parsed.to_dict()).to_dict())
        first = compile_capabilities(parsed, 'flatpak')
        raw['permissions']['requests'].reverse()
        raw['execution']['targets'].reverse()
        self.assertEqual(first['contractDigest'], compile_capabilities(raw, 'flatpak')['contractDigest'])

    def test_same_requested_contract_three_targets(self):
        plans = [compile_capabilities(recipe(), target) for target in ['oci', 'flatpak', 'appimage']]
        self.assertEqual(len({p['contractDigest'] for p in plans}), 1)
        self.assertTrue(all(p['launchAllowed'] for p in plans))
        flags = flatpak_permissions(plans[1])
        self.assertIn('--device=all', flags)
        self.assertIn('--share=network', flags)
        self.assertIn('--unshare=ipc', flags)
        self.assertNotIn('--share=ipc', flags)
        self.assertIn('--filesystem=xdg-documents/Harmony:create', flags)

    def test_strict_harmony_is_required_unsupported(self):
        raw = load_manifest(ROOT / 'docs/proposals/capability-parity/examples/myharmony.cage.yaml')
        p = compile_capabilities(raw, 'flatpak')
        self.assertFalse(p['launchAllowed'])
        with self.assertRaises(CapabilityError): flatpak_permissions(p)

    def test_denials_do_not_trigger_broad_fallback(self):
        r = load_manifest(ROOT / 'docs/proposals/capability-parity/examples/myharmony.cage.yaml').to_dict()
        r['execution']['fallbacks'] = [{'target':'flatpak','request':'harmony-usb','grant':{'kind':'device-class','class':'all'}}]
        p = compile_capabilities(r, 'flatpak')
        usb = next(x for x in p['requests'] if x['id'] == 'harmony-usb')
        self.assertEqual(usb['enforcement'], 'broader-accepted')
        self.assertEqual(usb['resolved']['interfaces'], ['hidraw','usb'])
        self.assertEqual(usb['resolved']['hotplug'], 'required')
        denied = compile_capabilities(r, 'flatpak', decisions={'harmony-usb':'deny'})
        item = next(x for x in denied['requests'] if x['id'] == 'harmony-usb')
        self.assertIsNone(item['fallback'])
        self.assertIsNone(item['grant'])
        self.assertFalse(denied['launchAllowed'])

    def test_optional_known_unsupported_omits_but_unknown_rejects(self):
        r = recipe()
        r['permissions']['requests'].append({'id':'camera','kind':'portal','interface':'camera','reason':'Optional camera'})
        p = compile_capabilities(r,'appimage')
        self.assertTrue(p['launchAllowed'])
        self.assertIsNone(next(x for x in p['requests'] if x['id']=='camera')['grant'])
        r['permissions']['requests'][-1]['kind']='host-command'
        with self.assertRaises(ManifestError): Manifest.from_dict(r)

    def test_required_hotplug_without_shared_event_namespace_refuses(self):
        r = recipe()
        r['permissions']['requests'] = [x for x in r['permissions']['requests'] if x['kind']!='network']
        self.assertFalse(compile_capabilities(r,'oci')['launchAllowed'])

    def test_rebinding_replaces_path_and_preserves_request(self):
        p = compile_capabilities(recipe(),'flatpak', bindings={'harmony-files':{'base':'xdg-documents','path':'Remote Backups'}})
        flags = flatpak_permissions(p)
        self.assertNotIn('--filesystem=xdg-documents/Harmony:create', flags)
        self.assertIn('--filesystem=xdg-documents/Remote Backups:create', flags)

    def test_protected_scope_and_overlap_refuse(self):
        r = recipe();files = next(x for x in r['permissions']['requests'] if x['kind']=='filesystem')
        files.update(required=True,location={'base':'absolute','path':'/proc'})
        self.assertFalse(compile_capabilities(r,'flatpak')['launchAllowed'])
        r = recipe();files = next(x for x in r['permissions']['requests'] if x['kind']=='filesystem')
        duplicate = {**files,'id':'read-files','access':'read-only','create':False}
        r['permissions']['requests'].append(duplicate)
        with self.assertRaises(CapabilityError): compile_capabilities(r,'oci')

    def test_malformed_or_removed_fields_reject(self):
        cases = []
        def case(change):
            r = recipe();change(r);cases.append(r)
        for key,value in [('network','none')]:
            case(lambda r: r['runtime'].update({key:value}))
        for value in ['required','host-access-accepted','auto']:
            case(lambda r,value=value: r['execution'].update(isolation=value))
        case(lambda r: r['permissions']['requests'][0].update(mode='enabled'))
        case(lambda r: r['permissions']['requests'][0].update(required='yes'))
        case(lambda r: r['permissions']['requests'][0].update(reason='trailing\n'))
        case(lambda r: r['permissions']['requests'].append(copy.deepcopy(r['permissions']['requests'][0])))
        case(lambda r: r['permissions']['requests'][0].update(kind=[]))
        case(lambda r: r.update(id='different.application.ID'))
        for r in cases:
            with self.subTest(r=r), self.assertRaises((ManifestError, CapabilityError)):
                Manifest.from_dict(r)

    def test_json_duplicate_keys_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'recipe.json'
            p.write_text(json.dumps(recipe()).replace('"schemaVersion": "cage.app/v1"','"schemaVersion": "cage.app/v1", "schemaVersion": "cage.app/v1"'))
            with self.assertRaisesRegex(ManifestError,'duplicate JSON'): load_manifest(p)


if __name__ == '__main__': unittest.main()
