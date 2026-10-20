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
from artifact.appimage import stage_notices
from runtime import desktop_launch
from runtime.desktop_launch import DesktopError, digest_json
from tests.test_desktop_export import bundle_at

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('appimage_launch', ROOT / 'runtime/appimage_launch.py')
integration = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'desktop_launch': desktop_launch}):
    spec.loader.exec_module(integration)


class AppImageTests(unittest.TestCase):
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

    def test_glibc_abi_diagnostic_precedes_python(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            plan = create_appimage_export_plan(bundle, allow_host_access=True)
            script = Path(td) / 'AppRun'
            script.write_text(apprun_script(plan))
            fake = Path(td) / 'bin'
            fake.mkdir()
            for name, output in [('uname', 'x86_64'), ('getconf', 'glibc 2.39')]:
                path = fake / name
                path.write_text('#!/bin/sh\necho "' + output + '"\n')
                path.chmod(0o755)
            result = subprocess.run(['/bin/sh', str(script)], env={'PATH': str(fake)}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('requires glibc 2.43', result.stderr)
            self.assertNotIn('python', result.stderr)


if __name__ == '__main__':
    unittest.main()
