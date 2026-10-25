"""Opt-in native namespace component probe, not Wine/three-format qualification."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from artifact.managed_launch import bubblewrap_args, seccomp_fd
from core.capabilities import compile_capabilities
from tests.test_capability_contract import recipe

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('CAGE_NATIVE_COMPONENT_TESTS')=='1','opt-in native namespace component probe')
class NativeNamespaceComponentTests(unittest.TestCase):
    def test_actual_filesystem_and_privilege_boundary(self):
        with tempfile.TemporaryDirectory(prefix='cage-native-component-') as temp:
            root=Path(temp);appdir=root/'app';prepared=root/'prepared';state=root/'state'
            for path in (appdir,prepared,state):path.mkdir()
            shutil.copyfile(ROOT/'tests/probes/capability_probe.py',appdir/'probe.py')
            read=root/'read';write=root/'write';denied=root/'denied';protected=root/'protected'
            for path in (read,write,denied,protected):path.mkdir()
            for path in (read,denied,protected):(path/'canary').write_bytes(b'cage-probe-canary\n')
            raw=recipe();raw['permissions']['requests']=[x for x in raw['permissions']['requests'] if x['kind']=='filesystem']
            plan=compile_capabilities(raw,'appimage');app=raw['id']
            release={'manifest':{'application':{'id':app}},'entry':{'format':'appimage','plan':{'desktop':{'id':app}}}}
            paths=[{'host':str(read),'access':'read-only','granted':True,'wineDrive':None},
                   {'host':str(write),'access':'read-write','granted':True,'wineDrive':None}]
            effective={'capabilities':plan,'paths':paths,'display':None,'digest':'a'*64}
            with seccomp_fd() as filter_file:
                args=bubblewrap_args(release,appdir,prepared,state,effective,filter_file.fileno())
                # A fixture OS runtime replaces the AppImage's private Python
                # closure only in this component test. Its scope is explicit.
                end=args.index('/run/cage/native/usr/python/bin/python3')
                args=args[:end]
                for source in ('/usr','/lib','/lib64'):
                    if Path(source).exists():args+=['--ro-bind',source,source]
                args+=['/usr/bin/python3','-I','/app/probe.py','--read',str(read/'canary'),'--write',str(write),
                       '--denied',str(denied/'canary'),'--protected',str(protected/'canary'),'--package','/app','--runtime','/run/cage/native']
                result=subprocess.run(args,capture_output=True,text=True,pass_fds=(filter_file.fileno(),),stdin=subprocess.DEVNULL,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertTrue(all(report['baseline'].values()))
            self.assertEqual(report['filesystem'],{'read':True,'readScopeMutation':False,'write':True,'siblingRead':False,
                              'protectedRead':False,'packageMutation':False,'runtimeMutation':False})
            self.assertEqual((read/'canary').read_bytes(),b'cage-probe-canary\n')
