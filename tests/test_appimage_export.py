"""AppImage policy, relocation, dependency resolution and non-destructive integration."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from artifact.appimage import (create_appimage_export_plan, apprun_script, checked_download,
                              unpack_python, stage_native_libraries)
from artifact.appimage import stage_notices, omit_unqualified_modules, relocate_wine_links, platform_directory
from artifact.appimage import stage_private_runtime
from runtime.appimage_runtime import materialize, interpreter_slot
from runtime import desktop_launch
from runtime.desktop_launch import DesktopError, digest_json
from tests.test_desktop_export import bundle_at

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('appimage_launch', ROOT / 'runtime/appimage_launch.py')
integration = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'desktop_launch': desktop_launch}):
    spec.loader.exec_module(integration)


class AppImageTests(unittest.TestCase):
    def test_absolute_platform_data_link_uses_pinned_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'platform'
            (root / 'share/X11').mkdir(parents=True)
            target = root / 'share/xkeyboard-config-2'
            target.mkdir()
            (target / 'proof').write_text('pinned data')
            (root / 'share/X11/xkb').symlink_to('/usr/share/xkeyboard-config-2')
            resolved = platform_directory(root, 'share/X11/xkb')
            self.assertEqual((resolved / 'proof').read_text(), 'pinned data')
            (root / 'share/X11/unsafe').symlink_to('/etc')
            with self.assertRaisesRegex(DesktopError, 'unexpected'):
                platform_directory(root, 'share/X11/unsafe')

    def test_only_known_wine_root_links_are_relocated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'wine'
            (root / 'bin').mkdir(parents=True)
            (root / 'bin/7zz').write_text('payload tool')
            (root / 'bin/7z').symlink_to('/app/bin/7zz')
            links = relocate_wine_links(root)
            self.assertEqual((root / 'bin/7z').read_text(), 'payload tool')
            self.assertEqual(links[0]['target'], '7zz')
            (root / 'bin/unsafe').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(DesktopError, 'non-portable'):
                relocate_wine_links(root)

    def test_media_exclusion_is_bounded_and_records_original_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            wine = Path(td) / 'wine'
            media = wine / 'lib/wine/x86_64-unix/winedmo.so'
            media.parent.mkdir(parents=True)
            media.write_bytes(b'optional media module')
            core = media.with_name('ntdll.so')
            core.write_bytes(b'retain core')
            omitted = omit_unqualified_modules(wine, ['winedmo.so'])
            self.assertFalse(media.exists())
            self.assertEqual(core.read_bytes(), b'retain core')
            self.assertEqual(omitted[0]['path'], 'lib/wine/x86_64-unix/winedmo.so')
            self.assertEqual(len(omitted[0]['sha256']), 64)
            with self.assertRaisesRegex(DesktopError, 'unknown'):
                omit_unqualified_modules(wine, ['ntdll.so'])

    def test_platform_notices_are_relocated_without_host_links(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source'
            (source / 'common').mkdir(parents=True)
            (source / 'common/license').write_text('notice')
            (source / 'package').mkdir()
            (source / 'package/COPYING').symlink_to('/usr/share/licenses/common/license')
            target = Path(td) / 'destination'
            stage_notices(source, target)
            self.assertEqual((target / 'package/COPYING').read_text(), 'notice')
            self.assertFalse(os.path.isabs(os.readlink(target / 'package/COPYING')))

    @unittest.skipUnless(shutil.which('gio'), 'requires desktop-entry execution tool')
    def test_desktop_exec_roundtrips_literal_special_characters(self):
        with tempfile.TemporaryDirectory(prefix='Cage café % " $ ` \\') as td:
            root = Path(td)
            executable = root / 'application'
            receipt = root / 'argv'
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAGE_TEST_ARGV"\n')
            executable.chmod(0o755)
            document = root / 'document café %.txt'
            document.touch()
            desktop = root / 'fixture.desktop'
            desktop.write_text('[Desktop Entry]\nType=Application\nName=Fixture\nExec=/usr/bin/env '
                               + integration.desktop_quote(executable) + ' -- %F\nTerminal=false\n')
            result = subprocess.run(['gio', 'launch', str(desktop), str(document)],
                           env={**os.environ, 'CAGE_TEST_ARGV': str(receipt)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + desktop.read_text())
            import time
            end = time.monotonic() + 5
            while not receipt.exists() and time.monotonic() < end:
                time.sleep(0.02)
            self.assertEqual(receipt.read_text().splitlines(), ['--', str(document)])

    def test_explicit_host_access_and_state_separation(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            with self.assertRaisesRegex(DesktopError, 'allow-host-access'):
                create_appimage_export_plan(bundle)
            plan = create_appimage_export_plan(bundle, allow_host_access=True)
            self.assertEqual(plan['state']['namespace'], 'cage/appimage')
            self.assertEqual(plan['permissions']['network'], 'host')
            self.assertFalse(plan['permissions']['recipeNetworkPolicyEnforced'])
            self.assertEqual(plan['target']['sourceTargetDigest'], digest_json(plan['sourceTarget']))
            self.assertNotEqual(plan['target'], plan['sourceTarget'])
            self.assertIn('usr/python/bin/python3', apprun_script(plan))

    def test_appimage_cli_plan_does_not_create_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            output = Path(td) / 'absent.AppImage'
            command = [sys.executable, '-m', 'cage', 'export', 'appimage', str(bundle),
                       '--dry-run', '--allow-host-access', '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['format'], 'appimage')
            self.assertFalse(output.exists())

    def test_tampered_tool_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            sha = 'a' * 64
            (Path(td) / sha).write_text('tampered')
            with self.assertRaisesRegex(DesktopError, 'checksum'):
                checked_download({'url': 'https://invalid.invalid', 'sha256': sha}, td)

    def test_python_archive_cannot_escape(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / 'python.tar.gz'
            with tarfile.open(archive, 'w:gz') as handle:
                member = tarfile.TarInfo('../escape')
                member.size = 1
                handle.addfile(member, io.BytesIO(b'x'))
            with self.assertRaisesRegex(DesktopError, 'unsafe'):
                unpack_python(archive, Path(td) / 'output')
            self.assertFalse((Path(td) / 'escape').exists())

    def test_integration_handles_special_paths_and_retains_state(self):
        with tempfile.TemporaryDirectory(prefix='Cage café % ') as td:
            root = Path(td)
            (root / 'org.example.App.svg').write_text('<svg/>')
            source = root / 'source.AppImage'
            source.write_bytes(b'\x7fELFtest package')
            data = root / 'data " $ ` %'
            plan = {'desktop': {'id': 'org.example.App', 'name': 'Fixture', 'summary': 'Fixture',
                                'categories': ['Utility']}}
            env = {'XDG_DATA_HOME': str(data), 'APPIMAGE': str(source)}
            with patch.dict(os.environ, env):
                result = integration.integrate(root, plan)
                desktop = Path(result['desktop'])
                contents = desktop.read_text()
                self.assertIn('%%', contents)
                self.assertIn('\\$', contents)
                self.assertIn(' -- %F', contents)
                state = data / 'cage/appimage/org.example.App/user-document'
                state.parent.mkdir(parents=True)
                state.write_text('preserve')
                with self.assertRaisesRegex(DesktopError, 'already exists'):
                    integration.integrate(root, plan)
                installed = Path(result['installed'])
                installed.write_bytes(b'changed')
                with self.assertRaisesRegex(DesktopError, 'changed'):
                    integration.integrate(root, plan, remove=True)
                installed.write_bytes(source.read_bytes())
                integration.integrate(root, plan, remove=True)
                self.assertFalse(desktop.exists())
                self.assertFalse(installed.exists())
                self.assertEqual(state.read_text(), 'preserve')

    def test_bootstrap_uses_private_loader_without_host_glibc_probe(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            plan = create_appimage_export_plan(bundle, allow_host_access=True)
            script = Path(td) / 'AppRun'
            script.write_text(apprun_script(plan))
            loader = Path(td) / 'usr/lib/cage-native/ld-linux-x86-64.so.2'
            loader.parent.mkdir(parents=True)
            loader.write_text('#!/bin/sh\n[ -z "${LD_LIBRARY_PATH-}" ] || exit 9\nprintf "%s\\n" "$@"\n')
            loader.chmod(0o755)
            with patch.dict(os.environ, {'LD_LIBRARY_PATH': '/host/injected'}):
                result = subprocess.run(['/bin/sh', str(script)], capture_output=True, text=True)
            # The fixture plan is x86_64 even when unit tests run on ARM.
            if os.uname().machine == 'x86_64':
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--library-path', result.stdout)
                self.assertIn('usr/python/bin/python3', result.stdout)
            self.assertNotIn('getconf', script.read_text())
            self.assertNotIn('minimumGlibc', plan['target'])
            self.assertIn('privateRuntime', plan['target'])

    @unittest.skipUnless(shutil.which('cc') and shutil.which('patchelf'), 'requires ELF producer tools')
    def test_private_runtime_relocates_and_child_exec_uses_packaged_libc(self):
        with tempfile.TemporaryDirectory(prefix='Cage runtime café ') as td:
            root = Path(td)
            source = root / 'old AppDir'
            binary = source / 'usr/wine/bin/probe'
            binary.parent.mkdir(parents=True)
            (source / 'usr/python').mkdir()
            native = source / 'usr/lib/cage-native'
            native.mkdir(parents=True)
            (source / 'usr/libexec').mkdir()
            code = root / 'probe.c'
            code.write_text('#define _GNU_SOURCE\n#include <stdio.h>\n#include <unistd.h>\n#include <dlfcn.h>\n'
                            'int main(int argc,char **argv){ if(argc==1){char *a[]={argv[0],"child",NULL};'
                            'execv(argv[0],a);return 3;} Dl_info i; if(!dladdr(dlsym(RTLD_NEXT,"printf"),&i))return 4;'
                            'char p[4096]; int n=readlink("/proc/self/exe",p,4095);if(n<0)return 5;'
                            'p[n]=0;printf("%s\\n%s\\n",i.dli_fname,p);return 0;}')
            subprocess.run(['cc', str(code), '-ldl', '-o', str(binary)], check=True)
            start, size = interpreter_slot(binary)
            with binary.open('rb') as handle:
                handle.seek(start)
                loader = Path(os.fsdecode(handle.read(size).rstrip(b'\0')))
            libc = subprocess.check_output(['cc', '-print-file-name=libc.so.6'], text=True).strip()
            shutil.copyfile(libc, native / 'libc.so.6')
            platform_root = root / 'platform'
            triplet = {'x86_64': 'x86_64-linux-gnu', 'aarch64': 'aarch64-linux-gnu'}[os.uname().machine]
            (platform_root / 'lib' / triplet).mkdir(parents=True)
            shutil.copy2(loader, platform_root / 'lib' / triplet / loader.name)
            (source / 'usr/wine/bin/alias').symlink_to('probe')
            manifest = stage_private_runtime(source, platform_root, os.uname().machine)
            moved = root / 'relocated AppDir'
            source.rename(moved)
            scratch = root / 'launch tree'
            scratch.mkdir()
            materialize(moved, scratch, manifest)
            result = subprocess.run([str(scratch / 'usr/wine/bin/alias')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('cage-native/libc.so.6', result.stdout)
            self.assertIn(str(scratch / 'usr/wine/bin/probe'), result.stdout)
            # A changed immutable executable must not be copied into the launch tree.
            with (moved / 'usr/wine/bin/probe').open('ab') as handle:
                handle.write(b'tamper')
            bad = root / 'bad launch'
            bad.mkdir()
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                materialize(moved, bad, manifest)


if __name__ == '__main__':
    unittest.main()
