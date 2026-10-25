"""Trust/state/native-control boundaries. No application or physical-device claims."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact import authority, permissions, releases as r, release_v2, managed_launch
from artifact import capability_runtime as host
from core.capabilities import compile_capabilities
from runtime.desktop_launch import plan_identity, prepare_generation, inventory_tree, digest_json, DesktopError
from runtime.capability_guard import check, policy_snapshot, policy_digest
from tests.test_capability_contract import recipe


def plan(kind='appimage'):
    source=recipe()
    return {'format':kind,'recipe':source,'desktop':source['desktop'], 'application':{'name':source['name'],'version':source['version']},
            'seedDigest':'1'*64,'sourceManifestDigest':digest_json(source),'launch':source['launch'],'environment':{},
            'target':{'architecture':'x86_64','runtime':{'image':'sha256:'+'a'*64,'network':'host'}},
            'state':{'managerVersion':2},'capabilities':compile_capabilities(source,kind),
            'runtimeClosureDigest':'2'*64,'materializerABI':'cage.elf-materializer/v1','managedNamespace':True}


class CapabilityDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'HOME':str(self.root/'home'),'XDG_DATA_HOME':str(self.root/'data')})
        self.env.start();self.addCleanup(self.env.stop)
        self.app=recipe()['id']

    def key(self,name):
        if importlib.util.find_spec('cryptography') is None:self.skipTest('install cage[releases] for signature tests')
        private=self.root/(name+'.key');public=self.root/(name+'.pub')
        r.generate_key(private,public)
        return public

    def test_canonical_authority_shared_formats_rejects_takeover_and_cache_bypass(self):
        key=self.key('publisher');other=self.key('other')
        cache=self.root/'cache'
        authority.claim(self.app,key,'appimage',cache)
        with patch.object(authority,'flatpak_refs',return_value=[]):authority.claim(self.app,key,'flatpak',cache)
        self.assertEqual(set(authority.read_authority(self.app)['formats']),{'appimage','flatpak'})
        with self.assertRaisesRegex(r.ReleaseError,'different publisher'):authority.claim(self.app,other,'oci',cache)
        with self.assertRaisesRegex(r.ReleaseError,'another cache'):authority.claim(self.app,key,'appimage',self.root/'alternate')
        self.assertEqual(authority.registered(self.app,'flatpak')[1],cache)
        authority.claim(self.app+'.Fresh',other,'appimage',self.root/'alternate')

    def test_native_flatpak_conflict_and_untracked_data_refuse_without_reset(self):
        key=self.key('publisher');cache=self.root/'cache'
        ref={'ref':self.app+'/x86_64/stable','origin':'test','installation':'user'}
        with patch.object(authority,'flatpak_refs',return_value=[ref,{**ref,'installation':'system'}]):
            with self.assertRaisesRegex(r.ReleaseError,'another Flatpak'):authority.claim(self.app,key,'flatpak',cache)
        with patch.object(authority,'flatpak_refs',return_value=[ref]):
            with self.assertRaisesRegex(r.ReleaseError,'verified adoption'):authority.claim(self.app,key,'flatpak',cache)
        self.assertIsNone(authority.read_authority(self.app))
        with self.assertRaisesRegex(r.ReleaseError,'verified adoption'):authority.claim(self.app,key,'appimage',cache,occupied=True)

    def test_policy_changes_do_not_change_v2_compatibility_but_runtime_does(self):
        first=plan();second=copy.deepcopy(first)
        second['recipe']['permissions']['requests']=[r for r in second['recipe']['permissions']['requests'] if r['kind']!='network']
        second['sourceManifestDigest']='f'*64;second['target']['runtime']['network']='none'
        second['state']['launcherSha256']='changed';second['layout']={'runtime':'/different/cache/path'}
        self.assertEqual(plan_identity(first),plan_identity(second))
        second['runtimeClosureDigest']='e'*64
        self.assertNotEqual(plan_identity(first),plan_identity(second))
        second=copy.deepcopy(first);second['launch']['args']=['changed']
        self.assertNotEqual(plan_identity(first),plan_identity(second))
        legacy=copy.deepcopy(first);legacy['state']['managerVersion']=1
        self.assertEqual(plan_identity(legacy)['schemaVersion'],'cage.desktop-state/v1')
        self.assertNotEqual(plan_identity(legacy),plan_identity(first))

    def test_permission_update_keeps_prefix_and_recovery_and_refuses_unknown_transition(self):
        seed=self.root/'seed';(seed/'drive_c').mkdir(parents=True)
        (seed/'drive_c/proof').write_text('seed')
        inventory=inventory_tree(seed);first=plan();first['seedDigest']=digest_json(inventory)
        state=self.root/'state';state.mkdir()
        prefix,pending=prepare_generation(seed,inventory,state,plan_identity(first),first,'launch')
        self.assertIsNone(pending);(prefix/'drive_c/proof').write_text('user settings')
        (state/'retained-recovery').write_text('keep')
        before=(state/'state.json').read_bytes()
        second=copy.deepcopy(first);second['capabilities']={'changed':'permission-only'}
        same,pending=prepare_generation(seed,inventory,state,plan_identity(second),second,'update')
        self.assertEqual(same,prefix);self.assertIsNone(pending)
        self.assertEqual((state/'state.json').read_bytes(),before)
        self.assertEqual((prefix/'drive_c/proof').read_text(),'user settings')
        second['runtimeClosureDigest']='changed'
        with self.assertRaisesRegex(DesktopError,'unqualified'):prepare_generation(seed,inventory,state,plan_identity(second),second,'update')
        self.assertEqual((state/'retained-recovery').read_text(),'keep')

    def test_exact_release_pointers_disambiguate_equal_compatibility(self):
        p=plan();identity=plan_identity(p);releases={}
        record={'schemaVersion':release_v2.SCHEMA,'applicationId':self.app,'publisherKeySha256':'a'*64,
                'releases':['1'*64,'2'*64],'activeReleaseDigest':'2'*64,'previousReleaseDigest':'1'*64,'releaseBindings':{}}
        for value in record['releases']:
            rel={'digest':value,'manifest':{'application':{'id':self.app},'publisherKeySha256':'a'*64},'entry':{'identity':identity,'plan':p}}
            releases[value]=rel;record['releaseBindings'][value]=release_v2._binding(rel)
        with patch('artifact.release_install.retained',side_effect=lambda root,digest,key,kind:releases[digest]),patch('artifact.release_install._state',return_value=None):
            self.assertEqual(release_v2.selected(self.root,record,None,'appimage')['digest'],'2'*64)
            self.assertEqual(release_v2.selected(self.root,record,None,'appimage',previous=True)['digest'],'1'*64)
            record['releaseBindings']['2'*64]['publisherKeySha256']='b'*64
            with self.assertRaisesRegex(r.ReleaseError,'binding differs'):release_v2.selected(self.root,record,None,'appimage')

    def snapshot(self,filesystems):
        return {'digest':'a'*64,'policy':{'Context':{'filesystems':filesystems}}}

    def test_native_union_includes_independent_descendants_and_readonly_precedence(self):
        base=str(self.root/'Documents');old=Path(base)/'Harmony';new=Path(base)/'New'
        s=self.snapshot(str(old)+':rw;'+str(new)+':ro;'+str(new/'child')+':rw;')
        self.assertEqual(permissions.path_access(s,new),'read-only')
        self.assertEqual(permissions.path_access(s,new/'child'),'read-write')
        self.assertEqual(len(permissions.overlapping_native_grants(s,new)),2)
        s=self.snapshot('!'+str(old)+';'+str(old/'independent')+':rw;')
        self.assertIsNone(permissions.path_access(s,old))
        self.assertEqual(len(permissions.overlapping_native_grants(s,old)),1)

    def test_flatpak_bind_previews_then_adopts_only_its_receipt(self):
        p=plan('flatpak');rel={'digest':'d'*64,'entry':{'plan':p,'format':'flatpak'},'manifest':{'application':{'id':self.app}}}
        old=self.root/'old';new=self.root/'new';old.mkdir();new.mkdir()
        loc={'base':'absolute','path':str(old)};newloc={'base':'absolute','path':str(new)}
        request=next(x for x in p['recipe']['permissions']['requests'] if x['kind']=='filesystem');request['location']=loc
        before=self.snapshot(str(old)+':rw;');after=self.snapshot(str(new)+':rw;')
        record={'format':'flatpak'}
        with patch.object(permissions,'installed',return_value=(record,rel,self.root/'cache')),patch.object(permissions,'native_snapshot',return_value=before),patch('artifact.managed_launch.state_root',return_value=self.root/'state'):
            result=permissions.bind(self.app,'flatpak',request['id'],newloc)
            self.assertFalse(result['adopted']);self.assertIn('--nofilesystem='+str(old),result['nativeCommand'])
            self.assertFalse(permissions.bindings_path(self.app,'flatpak').exists())
        with patch.object(permissions,'installed',return_value=(record,rel,self.root/'cache')),patch.object(permissions,'native_snapshot',return_value=after),patch('artifact.managed_launch.state_root',return_value=self.root/'state'):
            result=permissions.bind(self.app,'flatpak',request['id'],newloc)
            self.assertTrue(result['adopted']);self.assertFalse(result['nativeOverridesWritten'])
            self.assertEqual(permissions.local_bindings(self.app,'flatpak')['bindings'][request['id']],newloc)

    def test_native_edit_race_during_bind_never_restores_native_permissions(self):
        p=plan('flatpak');request=next(x for x in p['recipe']['permissions']['requests'] if x['kind']=='filesystem')
        old=self.root/'old';new=self.root/'new';old.mkdir();new.mkdir();request['location']={'base':'absolute','path':str(old)}
        rel={'digest':'d'*64,'entry':{'plan':p,'format':'flatpak'},'manifest':{'application':{'id':self.app}}}
        after=self.snapshot(str(new)+':rw;');changed={**after,'digest':'b'*64}
        with patch.object(permissions,'installed',return_value=({},rel,self.root/'cache')),patch.object(permissions,'native_snapshot',side_effect=[after,changed]),patch('artifact.managed_launch.state_root',return_value=self.root/'state'):
            with self.assertRaisesRegex(r.ReleaseError,'changed during adoption'):permissions.bind(self.app,'flatpak',request['id'],{'base':'absolute','path':str(new)})
        self.assertFalse(permissions.bindings_path(self.app,'flatpak').exists())

    def test_host_alias_cannot_expose_trust_or_recovery(self):
        raw=recipe();request=next(x for x in raw['permissions']['requests'] if x['kind']=='filesystem')
        alias=self.root/'alias';alias.symlink_to(self.root/'data')
        request['location']={'base':'absolute','path':str(alias)}
        with self.assertRaisesRegex(r.ReleaseError,'protected'):host.resolve_files(compile_capabilities(raw,'appimage'),self.app)

    def test_guard_blocks_missing_baseline_and_native_policy_race(self):
        p=plan('flatpak');p['target']['platformCommit']='c'*64
        proc=self.root/'proc/self';proc.mkdir(parents=True)
        (proc/'status').write_text('NoNewPrivs:\t1\nCapEff:\t0000000000000000\nSeccomp:\t2\n')
        info=self.root/'flatpak-info';text='[Application]\nname='+self.app+'\n[Instance]\napp-commit='+'b'*64+'\nruntime-commit='+'c'*64+'\n[Context]\nshared=network;\n'
        info.write_text(text)
        env={'CAGE_MANAGED_V1':'1','CAGE_POLICY_DIGEST':policy_digest(policy_snapshot(text)),'CAGE_EXPECTED_FLATPAK_COMMIT':'b'*64}
        check(p,environment=env,proc=proc.parent,flatpak_info=info)
        info.write_text(text.replace('shared=network;','shared=network;ipc;'))
        with self.assertRaisesRegex(ValueError,'native permissions changed'):check(p,environment=env,proc=proc.parent,flatpak_info=info)
        with self.assertRaisesRegex(ValueError,'trusted host'):check(p,environment={},proc=proc.parent,flatpak_info=info)
        (proc/'status').write_text('NoNewPrivs: 0\nCapEff: 0\nSeccomp: 2\n')
        with self.assertRaisesRegex(ValueError,'baseline'):check(p,environment=env,proc=proc.parent,flatpak_info=info)

    def test_fixed_namespace_materializer_checks_only_permitted_bytes(self):
        import struct
        from runtime.appimage_runtime import materialize, INTERPRETER_PLACEHOLDER
        source=self.root/'source';native=source/'usr/lib/cage-native';native.mkdir(parents=True)
        binary=source/'usr/wine/bin/probe';binary.parent.mkdir(parents=True)
        header=bytearray(64);header[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<Q',header,32,64);struct.pack_into('<HH',header,54,56,1)
        program=bytearray(56);struct.pack_into('<I',program,0,3);struct.pack_into('<Q',program,8,120)
        reserved=os.fsencode(INTERPRETER_PLACEHOLDER)+b'\0';struct.pack_into('<Q',program,32,len(reserved))
        binary.write_bytes(header+program+reserved+b'payload');binary.chmod(0o755)
        loader=native/'ld-linux-x86-64.so.2';loader.write_bytes(b'loader')
        manifest={'schemaVersion':'cage.appimage-private-runtime/v1','loader':loader.relative_to(source).as_posix(),
                  'files':[{'path':p.relative_to(source).as_posix(),'interpreter':p==binary,'sha256':r.hash_file(p)} for p in (binary,loader)]}
        for name in ('one','relocated two'):
            output=self.root/name;output.mkdir();materialize(source,output,manifest,namespace_root='/app')
            managed_launch.verify_transform(source,output,manifest)
        self.assertEqual((self.root/'one'/binary.relative_to(source)).read_bytes(),(self.root/'relocated two'/binary.relative_to(source)).read_bytes())
        target=self.root/'one'/binary.relative_to(source)
        target.write_bytes(target.read_bytes()+b'tamper')
        with self.assertRaisesRegex(r.ReleaseError,'outside its permitted'):managed_launch.verify_transform(source,self.root/'one',manifest)
        manifest['files'][0]['interpreter']='yes'
        bad=self.root/'bad';bad.mkdir()
        with self.assertRaisesRegex(ValueError,'metadata'):materialize(source,bad,manifest,namespace_root='/app')

    def test_oci_uses_rootless_private_baseline_without_privileged_fallback(self):
        p=plan('oci');p['target']['platformCommit']='f'*64
        rel={'manifest':{'application':{'id':self.app}},'entry':{'plan':p,'format':'oci','imageId':'sha256:'+'a'*64}}
        effective={'digest':'d'*64,'capabilities':compile_capabilities(p['recipe'],'oci'),'paths':[],
                   'display':{'display':':1','socket':'/tmp/.X11-unix/X1','authority':str(self.root/'auth')}}
        info={'host':{'security':{'rootless':True},'ociRuntime':{'name':'crun'}}}
        record={'stateDirectory':str(self.root/'state')}
        class Result:stdout=json.dumps(info)
        with patch.object(managed_launch,'_tool',return_value='/usr/bin/podman'),patch.object(r,'command',return_value=Result()),patch('pathlib.Path.is_dir',return_value=True),patch.dict(os.environ,{'CONTAINER_HOST':'','DOCKER_HOST':''}):
            args=managed_launch.container_args(record,rel,effective,seccomp_profile='/trusted/profile.json')
        self.assertIn('--cap-drop=ALL',args);self.assertIn('--security-opt=no-new-privileges',args)
        self.assertIn('--ipc=private',args);self.assertIn('--network=host',args)
        self.assertIn('--mount=type=bind,source=/dev,destination=/dev',args)
        self.assertIn('--tmpfs=/dev/shm:rw,nosuid,nodev',args)
        self.assertFalse(any('label=disable' in a or a=='--privileged' or a==':z' for a in args))
        info['host']['security']['rootless']=False
        Result.stdout=json.dumps(info)
        with patch.object(managed_launch,'_tool',return_value='/usr/bin/podman'),patch.object(r,'command',return_value=Result()):
            with self.assertRaisesRegex(r.ReleaseError,'rootless'):managed_launch.container_args(record,rel,effective,seccomp_profile='/trusted/profile.json')

    def test_alternate_native_installation_cannot_reuse_authority(self):
        key=self.key('publisher')
        with patch.object(authority,'flatpak_refs',return_value=[]):
            authority.claim(self.app,key,'flatpak',self.root/'cache')
            with patch.dict(os.environ,{'FLATPAK_USER_DIR':str(self.root/'another-installation')}):
                with self.assertRaisesRegex(r.ReleaseError,'another native Flatpak'):
                    authority.claim(self.app,key,'flatpak',self.root/'cache')
                with self.assertRaisesRegex(r.ReleaseError,'installation differs'):authority.registered(self.app,'flatpak')

    def test_historical_revocations_are_retained_for_rollback(self):
        raw=recipe();local={'decisions':{'historical-network':'deny'},'bindings':{'historical-folder':{'base':'home','path':'Old'}}}
        self.assertEqual(permissions.applicable_inputs(raw,local),{'decisions':{},'bindings':{}})
        raw['permissions']['requests'].append({'id':'historical-network','kind':'network','reason':'Old request'})
        self.assertEqual(permissions.applicable_inputs(raw,local)['decisions'],{'historical-network':'deny'})
        self.assertEqual(local['decisions']['historical-network'],'deny')

    def test_registered_alternate_cache_is_protected_from_folder_grants(self):
        key=self.key('publisher');external=self.root/'external-cache'
        authority.claim(self.app+'.Other',key,'appimage',external)
        external.mkdir();raw=recipe();request=next(x for x in raw['permissions']['requests'] if x['kind']=='filesystem')
        request['location']={'base':'absolute','path':str(external)}
        with self.assertRaisesRegex(r.ReleaseError,'protected'):host.resolve_files(compile_capabilities(raw,'oci'),self.app,self.root/'current-cache')

    def test_creation_is_pending_until_successful_host_preflight(self):
        raw=recipe();request=next(x for x in raw['permissions']['requests'] if x['kind']=='filesystem')
        folder=self.root/'new-folder';request.update(required=True,location={'base':'absolute','path':str(folder)})
        paths=host.resolve_files(compile_capabilities(raw,'oci'),self.app,create=False)
        self.assertTrue(paths[0]['creationPending']);self.assertFalse(folder.exists())
        paths=host.resolve_files(compile_capabilities(raw,'oci'),self.app,create=True)
        self.assertTrue(folder.is_dir());self.assertIn('inode',paths[0])

    def test_modified_wine_aliases_are_preserved(self):
        from runtime.desktop_launch import configure_managed_drives
        prefix=self.root/'prefix';(prefix/'dosdevices').mkdir(parents=True)
        alias=prefix/'dosdevices/h:';alias.symlink_to('/user-change')
        (prefix/'.cage-capability-drives.json').write_text(json.dumps({'H':'/old'}))
        with self.assertRaisesRegex(DesktopError,'unowned'):configure_managed_drives(prefix,{'CAGE_WINE_DRIVES':json.dumps({'H':'/new'})})
        self.assertEqual(os.readlink(alias),'/user-change')

    def test_host_desktop_entry_uses_cage_and_preserves_user_edits(self):
        from artifact import desktop_integration
        key=self.key('publisher');cache=self.root/'cache'
        authority.claim(self.app,key,'appimage',cache)
        p=plan();rel={'manifest':{'application':{'id':self.app}},'entry':{'format':'appimage','plan':p}}
        executable=self.root/'host-cage';executable.write_text('host executable fixture')
        with patch.object(desktop_integration.shutil,'which',return_value=str(executable)),patch.object(desktop_integration,'refresh_desktop_cache'):
            result=desktop_integration.install(rel,cache)
            target=Path(result['path']);original=target.read_text()
            self.assertIn('release run',original);self.assertIn('--format appimage',original)
            self.assertNotIn('AppRun',original);self.assertNotIn('application.AppImage',original)
            target.write_text(original+'# user edit\n')
            self.assertEqual(desktop_integration.install(rel,cache)['status'],'conflict')
            self.assertTrue(target.read_text().endswith('# user edit\n'))

    def test_native_broader_folder_union_refuses_without_rewriting_it(self):
        raw=recipe();request=next(x for x in raw['permissions']['requests'] if x['kind']=='filesystem')
        granted=self.root/'granted';extra=self.root/'independent';granted.mkdir();extra.mkdir()
        request['location']={'base':'absolute','path':str(granted)}
        capabilities=compile_capabilities(raw,'flatpak');paths=host.resolve_files(capabilities,self.app)
        snapshot={'policy':{'Context':{'filesystems':str(granted)+':rw;'+str(extra)+':rw;',
                                    'shared':'network;','devices':'all;','sockets':'x11;'}},'digest':'f'*64}
        original=snapshot['policy']['Context']['filesystems']
        with patch.object(host,'native_snapshot',return_value=snapshot):
            with self.assertRaisesRegex(r.ReleaseError,'union exceeds'):host.native_policy({},capabilities,paths)
        self.assertEqual(snapshot['policy']['Context']['filesystems'],original)

    def test_existing_v1_format_authority_cannot_be_taken_over_by_v2(self):
        key=self.key('publisher');other=self.key('other')
        canonical=authority.authority_folder(self.app).parent.parent
        legacy=canonical/'installed'/self.app/'appimage/installation.json';legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({'schemaVersion':'cage.release-installation/v1','publisherKeySha256':r.public_key(other)[1]}))
        original=legacy.read_bytes()
        with self.assertRaisesRegex(r.ReleaseError,'existing format ledger'):authority.claim(self.app,key,'oci',self.root/'another-cache')
        self.assertIsNone(authority.read_authority(self.app));self.assertEqual(legacy.read_bytes(),original)

    def test_host_desktop_integration_imports_in_a_clean_process(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-c','from artifact.desktop_integration import install'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_import_rejects_non_type2_without_executing(self):
        package=self.root/'bad.AppImage';package.write_bytes(b'#!/bin/sh\nexit 100\n')
        with self.assertRaisesRegex(r.ReleaseError,'type-2'):managed_launch.squash_offset(package)


if __name__=='__main__':unittest.main()
