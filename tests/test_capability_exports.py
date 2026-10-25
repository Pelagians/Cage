"""v1 adapter wiring and signed contract tests; synthetic payloads are not qualification."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from artifact import releases as r
from artifact.bundle import create_bundle
from artifact.desktop import create_desktop_export_plan, desktop_target, seal_desktop_bundle
from artifact.flatpak import create_flatpak_export_plan
from artifact.appimage import create_appimage_export_plan, apprun_script
from artifact.oci import create_oci_export_plan
from runtime.container_state import managed_plan
from runtime.desktop_launch import digest_json, plan_identity
from core.manifest import Manifest
from tests.bundle_fixtures import materialize_runnable_prefix
from tests.test_capability_contract import recipe
from tests.test_capability_delivery import plan


class CapabilityExportTests(unittest.TestCase):
    def test_v1_desktop_export_native_metadata_and_host_appimage_path(self):
        with tempfile.TemporaryDirectory() as temp:
            raw=recipe();raw.pop('sources');raw.pop('modules')
            manifest=Manifest.from_dict(raw)
            bundle=create_bundle(manifest,Path(temp),dry_run=True)
            materialize_runnable_prefix(bundle,entrypoint=manifest.launch.entrypoint)
            exe=bundle/'prefix/drive_c/MyHarmony/MyHarmony.exe'
            binary=bytearray(128);binary[:2]=b'MZ';binary[60:64]=(64).to_bytes(4,'little');binary[64:70]=b'PE\0\0\x4c\x01';exe.write_bytes(binary)
            (bundle/'prefix/dosdevices').mkdir()
            seal_desktop_bundle(bundle,desktop_target(),{'wineVersion':'wine-11.0'})
            (bundle/'metadata/execution-target.json').write_text(json.dumps(desktop_target()))
            flatpak=create_flatpak_export_plan(bundle);appimage=create_appimage_export_plan(bundle)
            self.assertIn('--device=all',flatpak['permissions']);self.assertIn('--share=network',flatpak['permissions'])
            self.assertNotIn('--share=ipc',flatpak['permissions'])
            self.assertTrue(appimage['managedNamespace']);self.assertEqual(appimage['layout']['runtime'],'/run/cage/native/usr/wine')
            self.assertNotIn('exec ',apprun_script(appimage))
            self.assertEqual(flatpak['capabilities']['contractDigest'],appimage['capabilities']['contractDigest'])

    def test_v1_container_plan_reuses_managed_lifecycle_and_requires_pinned_image(self):
        with tempfile.TemporaryDirectory() as temp:
            raw=recipe();raw.pop('sources');raw.pop('modules')
            manifest=Manifest.from_dict(raw);bundle=create_bundle(manifest,Path(temp),dry_run=True)
            materialize_runnable_prefix(bundle,entrypoint=manifest.launch.entrypoint)
            graph_path=bundle/'metadata/graph.json';graph=json.loads(graph_path.read_text())
            for field in ('builderRuntime','runnerRuntime'):
                graph[field]['image']='ghcr.io/pelagians/cage-wine@sha256:'+'a'*64
            graph_path.write_text(json.dumps(graph))
            p=managed_plan(bundle)
            self.assertEqual(p['state']['managerVersion'],2)
            self.assertEqual(p['recipe']['schemaVersion'],'cage.app/v1')
            self.assertTrue(p['capabilities']['launchAllowed'])

    def signed_fixture(self,root):
        source=plan();source['state']['namespace']='cage/appimage';source['layout']={'runtime':'/run/cage/native/usr/wine'}
        package=root/'fixture.AppImage';package.write_bytes(b'\x7fELF synthetic unit fixture')
        receipt={'schemaVersion':'cage.appimage-export-result/v0','sha256':r.hash_file(package),'plan':source}
        Path(str(package)+'.json').write_text(json.dumps(receipt))
        host={'os':'ubuntu','version':'24.04','architecture':'x86_64','desktop':'x11','wine':'wine-11.0','kernel':'unit-fixture',
              'bootedNative':True,'apparmorEnabled':True,'tools':{'fixture':'1'},'securityPolicy':{'fixture':'unit-test-only'}}
        proof={'status':'passed','format':'appimage','architecture':'x86_64','pageSize':4096,'settingsPreserved':True,'documentsPreserved':True,'rollback':True,
               'sessions':[{'identity':plan_identity(source)}],'sourceArtifactHashes':{'baseline':r.hash_file(package)},
               'capabilityQualification':{'contractDigest':source['capabilities']['contractDigest'],'baseline':'cage.local-desktop/v1','host':host,
               'cases':{name:{'status':'passed','evidence':['synthetic unit fixture only']} for name in ('baseline','filesystem','network','devices','hotplug')}}}
        evidence=root/'evidence.json';evidence.write_text(json.dumps(proof))
        spec=root/'spec.json';spec.write_text(json.dumps({'sequence':1,'sourceRevision':'a'*40,'artifacts':[{'format':'appimage','path':package.name,'evidence':evidence.name}]}))
        private=root/'private.pem';public=root/'public.pem';r.generate_key(private,public)
        return source,proof,spec,private,public

    def test_signed_v2_contract_is_separate_and_v1_domain_cannot_authorize_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,proof,spec,private,public=self.signed_fixture(root)
            output=root/'release.json';r.create_release(spec,private,output)
            data=output.read_bytes();signature=Path(str(output)+'.sig').read_bytes()
            value=r.verify_manifest(data,signature,public)
            self.assertEqual(value['schemaVersion'],'cage.release/v2')
            self.assertEqual(value['artifacts'][0]['identity']['schemaVersion'],'cage.desktop-state/v2')
            key,_=r.signing_key(private)
            with self.assertRaisesRegex(r.ReleaseError,'signature'):r.verify_manifest(data,key.sign(b'Cage trusted release v1\0'+data),public)
            value['artifacts'][0]['plan']['capabilities']['launchAllowed']=False
            changed=r.canonical(value)
            with self.assertRaisesRegex(r.ReleaseError,'metadata'):r.verify_manifest(changed,key.sign(b'Cage trusted release v2\0'+changed),public)

    def test_blocked_service_and_container_userland_evidence_cannot_qualify_v2(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,proof,spec,private,public=self.signed_fixture(root)
            for field,value in [('status','runtime-passed-service-blocked'),('bootedNative',False),('hotplug','blocked')]:
                candidate=copy.deepcopy(proof)
                if field=='status':candidate['status']=value
                elif field=='bootedNative':candidate['capabilityQualification']['host'][field]=value
                else:candidate['capabilityQualification']['cases'][field]['status']=value
                (root/'evidence.json').write_text(json.dumps(candidate))
                with self.assertRaises(r.ReleaseError):r.create_release(spec,private,root/('rejected-'+field+'.json'))


if __name__=='__main__':unittest.main()
