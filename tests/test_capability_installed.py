"""Signing evidence stays scoped; installed/runtime claims require native CI."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_capability_delivery import plan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installed_probe', ROOT/'scripts/test-capability-installed.py')
installed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installed)


class InstalledProbeEvidenceTests(unittest.TestCase):
    def write(self, path, value):
        Path(path).write_text(json.dumps(value))

    def test_device_and_hotplug_are_blocked_even_when_synthetic_probe_passes(self):
        p = plan()
        # The installed suite deliberately signs a hardware-free probe recipe.
        p['recipe']['permissions']['requests'] = [r for r in p['recipe']['permissions']['requests'] if r['kind'] != 'device-class']
        release = {'entry': {'format': 'appimage', 'plan': p, 'package': {'sha256': 'a'*64}}}
        sessions = [{'status': 'passed', 'settingsPreserved': True, 'stateCounter': i, 'operation': 'policy-rollback'} for i in (4,5,6)]
        with tempfile.TemporaryDirectory() as tmp:
            result = installed.proof(self, release, {}, sessions, Path(tmp)/'proof.json')
        cases = result['capabilityQualification']['cases']
        self.assertEqual(cases['devices']['status'], 'blocked')
        self.assertEqual(cases['hotplug']['status'], 'blocked')
        self.assertEqual(result['physicalUsbSynchronization'], 'unqualified')
        self.assertEqual(result['myHarmonyWorkflow'], 'not-qualified-by-probe-suite')
        self.assertEqual(set(k for k,v in cases.items() if v['status'] == 'passed'), {'baseline','filesystem','network'})

    def test_missing_or_failed_candidate_rollback_cannot_create_proof(self):
        release = {'entry': {'format': 'appimage', 'plan': plan(), 'package': {'sha256': 'a'*64}}}
        for sessions in ([], [{'status':'passed'}]*3, [{'status':'failed', 'settingsPreserved':True, 'stateCounter':i, 'operation':'policy-rollback'} for i in (4,5,6)]):
            with self.subTest(sessions=sessions), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)/'proof.json'
                with self.assertRaisesRegex(RuntimeError, 'actual compatible policy'):
                    installed.proof(self, release, {}, sessions, output)
                self.assertFalse(output.exists())

    def test_bundle_snapshot_excludes_sdk_staging_but_seals_prefix_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'prefix').mkdir(); (root/'prefix/settings').write_text('seed')
            (root/'metadata').mkdir(); (root/'metadata/seal.json').write_text('{}')
            sdk = root/'build/flatpak/files/bin'; sdk.mkdir(parents=True)
            (sdk/'tool').symlink_to('/usr/bin/tool')
            before = installed.bundle_inputs(root)
            (sdk/'unconsumed').write_text('build-only')
            self.assertEqual(installed.bundle_inputs(root), before)
            (root/'prefix/settings').write_text('changed')
            self.assertNotEqual(installed.bundle_inputs(root), before)
            (root/'prefix/escape').symlink_to('/usr/bin/tool')
            with self.assertRaisesRegex(ValueError, 'escaping payload symlink'):
                installed.bundle_inputs(root)

    def test_fresh_consumer_restores_environment_without_removing_state(self):
        import os
        before = dict(os.environ)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                with installed.fresh_consumer(root) as home:
                    sentinel = home/'recovery'; sentinel.write_bytes(b'retain')
                    self.assertEqual(Path.home(), home)
                    raise RuntimeError('interrupted')
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(sentinel.read_bytes(), b'retain')

class InstalledRecoveryTests(unittest.TestCase):
    def test_interrupted_install_recovery_completes_owned_desktop_registration(self):
        from unittest.mock import patch
        from artifact import release_v2, authority, release_install, desktop_integration
        from runtime.desktop_launch import _write_state_record
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); app = 'org.example.InstalledRecovery'; key = root/'publisher.pem'
            release = {'digest':'a'*64, 'entry':{'identity':{'same':'state'}, 'format':'appimage'},
                       'manifest':{'application':{'id':app}}}
            record = {'schemaVersion':release_v2.SCHEMA, 'pending':{'action':'install', 'acceptedContractDigest':'b'*64},
                      'publisherKeySha256':'c'*64}
            folder = root/'ledger';folder.mkdir()
            sentinel = root/'recovery';sentinel.write_text('retain original recovery')
            with patch.dict(os.environ, {'XDG_DATA_HOME':str(root/'data')}), \
                 patch.object(authority,'registered',return_value=({'publisherKeySha256':'c'*64},root,key)), \
                 patch.object(release_v2.r,'public_key',return_value=(None,'c'*64)), \
                 patch.object(release_install,'installation',return_value=folder), \
                 patch.object(release_install,'_read',return_value=record), \
                 patch.object(release_v2,'selected',return_value=release), \
                 patch.object(release_v2,'_safe_state'), \
                 patch.object(release_v2,'_install') as install, \
                 patch.object(release_v2,'_save_acceptance') as accept, \
                 patch.object(desktop_integration,'install',return_value={'status':'installed'}) as desktop:
                result=release_v2.operate(app,key,'appimage',root,action='recover')
                install.assert_called_once_with(record,release,folder,restore=True)
                accept.assert_called_once_with(release,'b'*64)
                desktop.assert_called_once_with(release,root)
                self.assertNotIn('pending',record)
                self.assertEqual(result['desktopIntegration']['status'],'installed')
                self.assertEqual(sentinel.read_text(),'retain original recovery')

    def test_flatpak_install_and_replacement_never_resolve_runtime_dependencies(self):
        from unittest.mock import patch
        from subprocess import CompletedProcess
        from artifact import release_v2, release_install, permissions, releases
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target={'platform':'org.freedesktop.Platform','architecture':'x86_64','branch':'25.08','platformCommit':'a'*64}
            rel={'directory':str(root),'entry':{'format':'flatpak','plan':{'target':target,'desktop':{'id':'org.example.Probe'},'branch':'stable'},
                 'flatpakCommit':'b'*64,'package':{'name':'probe.flatpak'}}}
            for existing in (False,True):
                for restore in (False,True):
                    with self.subTest(existing=existing,restore=restore), \
                         patch('subprocess.run',side_effect=[CompletedProcess([],0,'a'*64,''),CompletedProcess([],0 if existing else 1,'c'*64,'')]), \
                         patch.object(releases,'command') as command, \
                         patch.object(release_install,'_check_deployment'), \
                         patch.object(permissions,'native_snapshot'):
                        release_v2._install({},rel,root,restore=restore)
                        args=command.call_args.args[0]
                        self.assertIn('--no-deps',args)
                        self.assertEqual('--reinstall' in args,existing or restore)
                        self.assertNotIn('--or-update',args)

    def test_flatpak_wrong_platform_pin_refuses_before_app_deployment(self):
        from unittest.mock import patch
        from subprocess import CompletedProcess
        from artifact import release_v2, releases
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sentinel=root/'recovery';sentinel.write_text('keep')
            target={'platform':'org.freedesktop.Platform','architecture':'x86_64','branch':'25.08','platformCommit':'a'*64}
            release={'entry':{'format':'flatpak','plan':{'target':target}}}
            with patch('subprocess.run',return_value=CompletedProcess([],0,'wrong','')),patch.object(releases,'command') as command:
                with self.assertRaisesRegex(releases.ReleaseError,'runtime prerequisite differs'):
                    release_v2._install({},release,root)
                command.assert_not_called()
                self.assertEqual(sentinel.read_text(),'keep')
