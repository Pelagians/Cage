"""Real signature/transport tests plus deployment interruption boundaries."""
from contextlib import contextmanager
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    import cryptography
except ImportError:
    cryptography=None

from artifact import releases as r, release_install as delivery
from runtime.desktop_launch import plan_identity


@unittest.skipUnless(cryptography, 'install cage[releases] for signature qualification')
class TrustedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.private=self.root/'private.pem';self.key=self.root/'public.pem'
        r.generate_key(self.private,self.key)
        self.cache=self.root/'consumer'
        self.arch={'arm64':'aarch64','amd64':'x86_64'}.get(platform.machine(),platform.machine())
        self.old=self.release('1',1);self.new=self.release('2',2)

    def release(self, version, sequence, kind='appimage', runtime='same', **extra):
        folder=self.root/(kind+'-'+version);folder.mkdir()
        package=folder/('app-'+version+'.'+('AppImage' if kind=='appimage' else 'flatpak'))
        package.write_bytes(b'\x7fELF pinned application '+version.encode())
        plan={'format':kind,'branch':'stable','seedDigest':hashlib.sha256(version.encode()).hexdigest(),
              'sourceManifestDigest':'e'*64,'application':{'name':'proof','version':version},
              'target':{'architecture':self.arch,'runtimeRevision':runtime,'translation':{'hostPageSizes':[4096,16384]}},'state':{'managerVersion':1,'namespace':'cage/appimage'},
              'desktop':{'id':'org.example.Proof','updates':{'profile':'proof/v1','settings':[],'documents':[]}}}
        receipt={'schemaVersion':'cage.'+kind+'-export-result/v0','sha256':r.hash_file(package),'plan':plan,'commit':version*64}
        Path(str(package)+'.json').write_text(json.dumps(receipt))
        proof={'status':'passed','format':kind,'architecture':self.arch,'pageSize':os.sysconf('SC_PAGE_SIZE'),
               'settingsPreserved':True,'documentsPreserved':True,'rollback':True,'sessions':[{'identity':plan_identity(plan)}],
               'sourceArtifactHashes':{'baseline':r.hash_file(package)}}
        evidence=folder/'result.json';evidence.write_text(json.dumps(proof))
        spec={'sequence':sequence,'sourceRevision':'a'*40,'artifacts':[{'format':kind,'path':package.name,'evidence':evidence.name}],**extra}
        spec_path=folder/'spec.json';spec_path.write_text(json.dumps(spec))
        output=folder/'release.json';r.create_release(spec_path,self.private,output)
        return output

    def resign(self, path, edit=None, raw=None):
        manifest=r.parse(path.read_bytes())
        if edit:edit(manifest)
        data=raw if raw is not None else r.canonical(manifest)
        key,_=r.signing_key(self.private)
        path.write_bytes(data);Path(str(path)+'.sig').write_bytes(key.sign(b'Cage trusted release v1\0'+data))

    @contextmanager
    def server(self):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(self.root)))
        thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        try:yield 'http://127.0.0.1:'+str(httpd.server_port)
        finally:httpd.shutdown();httpd.server_close();thread.join()

    def test_real_signature_and_cached_offline_verification(self):
        value=r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
        with patch('artifact.releases.urlopen',side_effect=AssertionError('offline')):
            cached=r.cached_release(value['directory'],self.key,'appimage')
        self.assertEqual(cached['digest'],value['digest'])
        self.assertTrue((Path(value['directory'])/value['entry']['package']['name']).stat().st_mode&0o100)
        self.assertEqual(self.private.stat().st_mode&0o777,0o600)
        self.assertNotIn('PRIVATE KEY',self.old.read_text())

    def test_key_outputs_are_never_overwritten(self):
        with self.assertRaises(r.ReleaseError):r.generate_key(self.private,self.key)
        self.private.chmod(0o644)
        with self.assertRaisesRegex(r.ReleaseError,'0600'):r.signing_key(self.private)

    def test_wrong_key_and_metadata_tampering_never_download_assets(self):
        wrong=self.root/'wrong.pem';r.generate_key(self.root/'wrong-private.pem',wrong)
        with patch('artifact.releases._fetch_asset') as fetch:
            with self.assertRaisesRegex(r.ReleaseError,'signature'):r.fetch_release(self.old,wrong,'appimage',cache=self.cache)
            self.old.write_bytes(self.old.read_bytes()+b' ')
            with self.assertRaisesRegex(r.ReleaseError,'signature'):r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
            fetch.assert_not_called()

    def test_changed_package_retains_partial_and_retry_recovers(self):
        manifest=r.parse(self.old.read_bytes());asset=manifest['artifacts'][0]['package'];source=self.old.parent/asset['name']
        original=source.read_bytes();source.write_bytes(b'broken')
        with self.assertRaisesRegex(r.ReleaseError,'hash/size'):r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
        self.assertEqual(len(list(self.cache.rglob('*.partial'))),1)
        source.write_bytes(original)
        value=r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
        self.assertFalse(list(Path(value['directory']).glob('*.partial')))
        target=Path(value['directory'])/asset['name'];target.write_bytes(b'changed cached bytes')
        with self.assertRaisesRegex(r.ReleaseError,'changed'):r.cached_release(value['directory'],self.key,'appimage')

    def test_truncated_http_download_then_real_retry(self):
        with self.server() as base:
            value=r.fetch_release(base+'/'+self.old.relative_to(self.root).as_posix(),self.key,'appimage',cache=self.cache)
        self.assertEqual(value['manifest']['application']['version'],'1')
        # Transport interruption retains an unverified partial; a later fetch
        # restarts only that private partial and verifies all bytes again.
        other=self.root/'retry-cache';original=r.read_source
        class Broken:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):raise OSError('connection interrupted')
        asset=r.parse(self.new.read_bytes())['artifacts'][0]['package']['name']
        with patch('artifact.releases.read_source',side_effect=lambda src,n:Broken() if str(src).endswith(asset) else original(src,n)):
            with self.assertRaisesRegex(OSError,'interrupted'):r.fetch_release(self.new,self.key,'appimage',cache=other)
        self.assertTrue(list(other.rglob('*.partial')))
        r.fetch_release(self.new,self.key,'appimage',cache=other)

    def test_path_escape_duplicate_json_and_wrong_target_are_refused(self):
        data=self.old.read_bytes();sig=Path(str(self.old)+'.sig').read_bytes()
        for edit in (lambda m:m['artifacts'][0]['package'].update(name='../escape'),
                     lambda m:m['artifacts'][0].update(identity={}),
                     lambda m:m.update(sequence=True)):
            self.resign(self.old,edit)
            with self.assertRaises(r.ReleaseError):r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
            self.old.write_bytes(data);Path(str(self.old)+'.sig').write_bytes(sig)
        self.resign(self.old,raw=b'{"schemaVersion":"x","schemaVersion":"y"}')
        with self.assertRaisesRegex(r.ReleaseError,'duplicate'):r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
        self.old.write_bytes(data);Path(str(self.old)+'.sig').write_bytes(sig)
        with self.assertRaisesRegex(r.ReleaseError,'architecture'):
            r.fetch_release(self.old,self.key,'appimage',cache=self.cache,arch='aarch64' if self.arch=='x86_64' else 'x86_64')

    def test_low_space_and_linked_partial_never_deploy(self):
        with patch('artifact.releases.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
            with self.assertRaisesRegex(r.ReleaseError,'space'):r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
        manifest=r.parse(self.old.read_bytes());digest=hashlib.sha256(self.old.read_bytes()).hexdigest()
        folder=self.cache/'releases'/digest;asset=manifest['artifacts'][0]['evidence']
        outside=self.root/'outside';outside.write_text('safe')
        (folder/(asset['name']+'.partial')).symlink_to(outside)
        with self.assertRaises(OSError):r.fetch_release(self.old,self.key,'appimage',cache=self.cache)
        self.assertEqual(outside.read_text(),'safe')

    def test_unqualified_evidence_cannot_be_signed_or_cached(self):
        self.resign(self.old,lambda m:m['artifacts'][0]['evidence'].update(name=m['artifacts'][0]['package']['name'],**{k:m['artifacts'][0]['package'][k] for k in ('size','sha256')}))
        with self.assertRaises(r.ReleaseError):r.fetch_release(self.old,self.key,'appimage',cache=self.cache)

    def test_successful_evidence_for_different_package_cannot_authorize_release(self):
        evidence=self.old.parent/'result.json';proof=json.loads(evidence.read_text())
        proof['sourceArtifactHashes']={'baseline':'f'*64};evidence.write_text(json.dumps(proof))
        output=self.old.parent/'wrong-package.json'
        with self.assertRaisesRegex(r.ReleaseError,'exact package'):
            r.create_release(self.old.parent/'spec.json',self.private,output)
        self.assertFalse(output.exists())

    def test_https_required_and_cross_origin_redirect_refused(self):
        for source in ('http://example.org/release.json','https://user:secret@example.org/release.json','https://example.org/release.json?q=1'):
            with self.assertRaises(r.ReleaseError):r._origin(source)
        class Response:
            def geturl(self):return 'http://127.0.0.1:444/other'
            def close(self):pass
        with patch('artifact.releases.urlopen',return_value=Response()):
            with self.assertRaisesRegex(r.ReleaseError,'cross-origin'):r.read_source('https://example.org/release.json',10)

    def test_flatpak_commit_is_bound_in_signed_metadata(self):
        path=self.release('3',3,kind='flatpak');value=r.fetch_release(path,self.key,'flatpak',cache=self.cache)
        self.assertEqual(value['entry']['flatpakCommit'],'3'*64)

    def test_real_public_cli_keygen_create_fetch_info_errors(self):
        private=self.root/'cli-private.pem';public=self.root/'cli-public.pem'
        def cli(*args):
            return subprocess.run([sys.executable,'-m','cage','release',*map(str,args)],capture_output=True,text=True)
        result=cli('keygen','--private-key',private,'--public-key',public)
        self.assertEqual(result.returncode,0,result.stderr)
        output=self.old.parent/'cli-release.json'
        result=cli('create',self.old.parent/'spec.json','--private-key',private,'--output',output)
        self.assertEqual(result.returncode,0,result.stderr)
        result=cli('fetch',output,'--key',public,'--format','appimage','--cache-dir',self.cache)
        self.assertEqual(result.returncode,0,result.stderr)
        result=cli('info','org.example.NoInstall','--key',public,'--format','appimage','--cache-dir',self.cache)
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('Traceback',result.stderr)

    def fake_runtime(self):
        self.state=None;self.fail=None
        def launch(record,release,files,action=None,**kwargs):
            if self.fail=='before':raise r.ReleaseError('trial failed before commit')
            identity=release['entry']['identity']
            if self.state is None:self.state={'active':'prefix','generations':[{'prefix':'prefix','identity':identity}]}
            elif action:
                active='generation-'+str(len(self.state['generations']))
                self.state['previous']=self.state['active'];self.state['active']=active
                self.state['generations'].append({'prefix':active,'identity':identity})
            if self.fail=='after':raise r.ReleaseError('interrupted after commit')
        for target,value in (('_install',lambda *a:None),('_state',lambda *a:self.state),('_launch',launch)):
            p=patch('artifact.release_install.'+target,side_effect=value);p.start();self.addCleanup(p.stop)

    def install_run(self):
        delivery.deploy(self.old,self.key,'appimage',cache=self.cache)
        delivery.operate('org.example.Proof',self.key,'appimage',cache=self.cache)

    def test_signed_install_update_rollback_relaunch_keeps_high_water(self):
        self.fake_runtime();self.install_run()
        delivery.deploy(self.new,self.key,'appimage',action='update',cache=self.cache)
        delivery.operate('org.example.Proof',self.key,'appimage',action='rollback',cache=self.cache)
        info=delivery.operate('org.example.Proof',self.key,'appimage',action='info',cache=self.cache)
        self.assertEqual((info['activeVersion'],info['highWater']),('1',2))
        with patch('artifact.releases._fetch_asset') as download:
            with self.assertRaisesRegex(r.ReleaseError,'stale'):delivery.deploy(self.old,self.key,'appimage',action='update',cache=self.cache)
            download.assert_not_called()

    def test_unqualified_runtime_change_refused_before_trial_or_high_water_change(self):
        self.fake_runtime();self.install_run();other=self.release('3',3,runtime='different')
        with patch('artifact.release_install._launch') as launch:
            with self.assertRaisesRegex(r.ReleaseError,'runtime or migration'):delivery.deploy(other,self.key,'appimage',action='update',cache=self.cache)
            launch.assert_not_called()
        self.assertEqual(delivery.operate('org.example.Proof',self.key,'appimage',action='info',cache=self.cache)['highWater'],1)

    def test_storage_reports_pending_release_recovery_without_pruning_history(self):
        self.fake_runtime();self.install_run();self.fail='before'
        with self.assertRaises(r.ReleaseError):delivery.deploy(self.new,self.key,'appimage',action='update',cache=self.cache)
        from artifact.storage import storage_status
        report=storage_status(output_dir=self.root/'empty',package_dirs=[self.cache])
        release=[p for p in report['packages'] if p['category']=='trusted-release-cache'][0]
        self.assertTrue(release['protected'])
        self.assertIn('cage release recover',release['installations'][0]['recoveryHint'])
        self.assertEqual(len(list((self.cache/'releases').iterdir())),2)

    def test_failed_trial_and_post_commit_interruption_recover_from_actual_state(self):
        for failure,expected in (('before','1'),('after','2')):
            with self.subTest(failure=failure):
                self.cache=self.root/('cache-'+failure);self.fake_runtime();self.install_run();self.fail=failure
                with self.assertRaises(r.ReleaseError):delivery.deploy(self.new,self.key,'appimage',action='update',cache=self.cache)
                with self.assertRaisesRegex(r.ReleaseError,'unfinished'):delivery.operate('org.example.Proof',self.key,'appimage',cache=self.cache)
                self.fail=None
                delivery.operate('org.example.Proof',self.key,'appimage',action='recover',cache=self.cache)
                info=delivery.operate('org.example.Proof',self.key,'appimage',action='info',cache=self.cache)
                self.assertEqual((info['activeVersion'],info['highWater']),(expected,2))

    def test_oci_mounts_keep_documents_and_state_separate_and_paths_scoped(self):
        release={'entry':{'imageId':'sha256:'+'a'*64}}
        record={'engine':'podman','stateDirectory':str(self.root/'state'),'exportsDirectory':str(self.root/'documents')}
        (self.root/'documents').mkdir();doc=self.root/'documents'/'café.pdf';doc.write_text('pdf')
        args=delivery._container_args(record,release,[doc],'update')
        self.assertIn('--network=none',args);self.assertIn('--pull=never',args)
        self.assertEqual(args[-3:],['--cage-update','--','/exports/café.pdf'])
        with self.assertRaisesRegex(r.ReleaseError,'exports directory'):delivery._container_args(record,release,[self.root/'secret'])

    def test_changed_installed_flatpak_commit_is_refused_before_any_helper_runs(self):
        self.fake_runtime();path=self.release('4',4,kind='flatpak')
        with patch('artifact.release_install._flatpak_commit',return_value='4'*64):
            delivery.deploy(path,self.key,'flatpak',cache=self.cache)
        with patch('artifact.release_install._flatpak_commit',return_value='f'*64),patch('artifact.release_install._state') as state:
            with self.assertRaisesRegex(r.ReleaseError,'commit'):delivery.operate('org.example.Proof',self.key,'flatpak',cache=self.cache)
            state.assert_not_called()

    def test_flatpak_recovery_refuses_foreign_commit_before_any_helper_runs(self):
        self.fake_runtime();path=self.release('5',5,kind='flatpak')
        delivery.deploy(path,self.key,'flatpak',cache=self.cache)
        folder=delivery.installation(self.cache,'org.example.Proof','flatpak')
        transaction=folder/'flatpak-transaction';transaction.mkdir()
        value=r.parse(path.read_bytes())['artifacts'][0]
        entry={'sha256':value['package']['sha256'],'identity':value['identity'],'plan':value['plan']}
        (transaction/'transaction.json').write_text(json.dumps({'candidate':entry,'previous':entry}))
        with patch('artifact.release_install._flatpak_commit',return_value='f'*64),patch('artifact.updates.recover_flatpak') as recover,patch('artifact.release_install._state') as state:
            with self.assertRaisesRegex(r.ReleaseError,'no recovery helper'):delivery.operate('org.example.Proof',self.key,'flatpak',action='recover',cache=self.cache)
            recover.assert_not_called();state.assert_not_called()


if __name__=='__main__':unittest.main()
