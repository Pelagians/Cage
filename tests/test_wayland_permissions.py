"""Native Wayland selection and refusal boundaries; actual windows run in CI."""
import copy
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from artifact import capability_runtime as host, managed_launch, releases
from artifact.desktop import validate_desktop_recipe
from core.capabilities import compile_capabilities, flatpak_permissions
from core.manifest import Manifest
from runtime.desktop_launch import verify_wayland_driver, DesktopError, plan_identity, prepare_generation, inventory_tree, digest_json
from tests.test_capability_contract import recipe
from tests.test_capability_delivery import plan


def wayland_recipe():
    raw=recipe();raw['runtime']['wineGraphics']='wayland'
    next(r for r in raw['permissions']['requests'] if r['kind']=='display')['backend']='wayland'
    return raw


class WaylandPermissionsTests(unittest.TestCase):
    def test_runtime_gate_is_explicit_and_never_falls_back_to_x11(self):
        raw=wayland_recipe()
        for kind in ('oci','flatpak','appimage'):
            self.assertTrue(compile_capabilities(raw,kind)['launchAllowed'])
        flags=flatpak_permissions(compile_capabilities(raw,'flatpak'))
        self.assertIn('--socket=wayland',flags);self.assertNotIn('--socket=x11',flags)
        for field,value in [('version','9.0'),('provider','staging'),('wineGraphics','xwayland')]:
            changed=copy.deepcopy(raw);changed['runtime'][field]=value
            result=compile_capabilities(changed,'flatpak')
            self.assertFalse(result['launchAllowed']);self.assertNotIn('--socket=x11',str(result))

    def test_target_identity_is_separate_and_legacy_target_unchanged(self):
        x11=validate_desktop_recipe(Manifest.from_dict(recipe()))
        wl=validate_desktop_recipe(Manifest.from_dict(wayland_recipe()))
        self.assertEqual(x11['graphics'],'x11');self.assertEqual(wl['graphics'],'wayland')
        self.assertEqual(x11['baseCommit'],wl['baseCommit']);self.assertNotEqual(x11['id'],wl['id'])
        bad=wayland_recipe();next(r for r in bad['permissions']['requests'] if r['kind']=='display')['backend']='x11'
        with self.assertRaises(DesktopError):validate_desktop_recipe(Manifest.from_dict(bad))

    def test_wayland_signing_needs_matching_host_and_display_evidence(self):
        raw=wayland_recipe();raw['permissions']['requests']=[r for r in raw['permissions']['requests'] if r['kind']=='display']
        caps=compile_capabilities(raw,'appimage')
        qualification={'contractDigest':caps['contractDigest'],'baseline':'cage.local-desktop/v1',
            'host':{'bootedNative':True,'architecture':'x86_64','os':'ubuntu','version':'24.04','desktop':'x11',
                    'wine':'wine-11.0','apparmorEnabled':True,'kernel':'fixture','tools':{'fixture':'1'},'securityPolicy':{'fixture':'unit-only'}},
            'cases':{name:{'status':'passed','evidence':['unit-only']} for name in ('baseline','filesystem','network')}}
        entry={'format':'appimage','plan':{'recipe':raw}}
        with self.assertRaises(releases.ReleaseError):releases.verify_capability_evidence(entry,{'capabilityQualification':qualification})
        qualification['host']['desktop']='wayland'
        with self.assertRaises(releases.ReleaseError):releases.verify_capability_evidence(entry,{'capabilityQualification':qualification})
        qualification['cases']['display']={'status':'passed','evidence':['unit-only']}
        releases.verify_capability_evidence(entry,{'capabilityQualification':qualification})

    def test_missing_or_ambiguous_driver_refuses_without_creating_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wine=root/'bin/wine';wine.parent.mkdir();wine.write_text('fixture')
            with self.assertRaisesRegex(DesktopError,'lacks'):verify_wayland_driver(wine)
            for suffix in ('x86_64-windows/winewayland.drv','x86_64-unix/winewayland.so'):
                p=root/'lib/wine'/suffix;p.parent.mkdir(parents=True);p.write_bytes(b'fixture')
            proof=verify_wayland_driver(wine);self.assertEqual(len(proof['files']),2)
            self.assertFalse((root/'prefix').exists())

    def test_owned_socket_only_and_replaced_socket_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'wayland-0'
            with socket.socket(socket.AF_UNIX) as server, patch.dict(os.environ,{'XDG_RUNTIME_DIR':tmp,'WAYLAND_DISPLAY':'wayland-0'}):
                server.bind(str(path));display=host.wayland()
                managed_launch.verify_display_socket(display)
                path.unlink();path.write_text('replacement')
                with self.assertRaisesRegex(releases.ReleaseError,'changed'):managed_launch.verify_display_socket(display)
                path.unlink();path.symlink_to(root/'other')
                with self.assertRaises(releases.ReleaseError):host.wayland()
                with patch.dict(os.environ,{'WAYLAND_DISPLAY':'../other'}):
                    with self.assertRaises(releases.ReleaseError):host.wayland()
                root.chmod(0o755)
                with self.assertRaisesRegex(releases.ReleaseError,'private'):host.wayland()

    def test_namespace_mounts_only_wayland_socket_and_no_xauthority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'wayland-0'
            with socket.socket(socket.AF_UNIX) as server, patch.dict(os.environ,{'XDG_RUNTIME_DIR':tmp,'WAYLAND_DISPLAY':'wayland-0'}):
                server.bind(str(path));raw=wayland_recipe()
                raw['permissions']['requests']=[r for r in raw['permissions']['requests'] if r['kind']=='display']
                release={'manifest':{'application':{'id':raw['id']}},'entry':{'format':'appimage','imageId':'sha256:'+'a'*64,'plan':{'desktop':{'id':raw['id']}}}}
                effective={'capabilities':compile_capabilities(raw,'appimage'),'paths':[],'display':host.wayland(),'digest':'a'*64}
                with patch.object(managed_launch,'_tool',side_effect=lambda n:n):
                    args=managed_launch.bubblewrap_args(release,root/'app',root/'native',root/'state',effective,9)
                    podman=type('Result',(),{'stdout':'{"host":{"security":{"rootless":true},"ociRuntime":{"name":"crun"}}}'})()
                    with patch.object(releases,'command',return_value=podman):
                        oci=managed_launch.container_args({'stateDirectory':str(root/'state')},release,effective,seccomp_profile=root/'filter')
                for command in (args,oci):
                    text=' '.join(command);self.assertIn('wayland-0',text)
                    self.assertNotIn('Xauthority',text);self.assertNotIn('.X11-unix',text);self.assertNotIn('DISPLAY=',text.replace('WAYLAND_DISPLAY=',''))
                self.assertIn(str(path),args);self.assertNotIn(tmp,args)

    def test_flatpak_native_x11_union_refuses_for_wayland(self):
        caps=compile_capabilities(wayland_recipe(),'flatpak')
        snapshot={'policy':{'Context':{'shared':'network;','devices':'all;','sockets':'wayland;'}},'digest':'a'*64}
        with patch.object(host,'native_snapshot',return_value=snapshot):
            host.native_policy({},caps,[])
            snapshot['policy']['Context']['sockets']='wayland;x11;'
            with self.assertRaisesRegex(releases.ReleaseError,'socket grant'):host.native_policy({},caps,[])

    def test_graphics_switch_refuses_and_preserves_prefix_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed=root/'seed';(seed/'drive_c').mkdir(parents=True);(seed/'user.reg').write_text('seed')
            inv=inventory_tree(seed);first=plan();first['target']['graphics']='x11';first['seedDigest']=digest_json(inv)
            state=root/'state';state.mkdir()
            prefix,_=prepare_generation(seed,inv,state,plan_identity(first),first,'launch')
            (prefix/'user.reg').write_text('saved preference');(state/'recovery').write_bytes(b'keep')
            before=inventory_tree(state,state_snapshot=True)
            second=copy.deepcopy(first);second['target']['graphics']='wayland'
            self.assertNotEqual(plan_identity(first),plan_identity(second))
            with self.assertRaisesRegex(DesktopError,'unqualified'):prepare_generation(seed,inv,state,plan_identity(second),second,'update')
            self.assertEqual(before,inventory_tree(state,state_snapshot=True))
