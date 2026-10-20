"""Desktop handoff and DPI behavior without touching normal user state."""
from pathlib import Path
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from artifact.desktop import stage_desktop_fonts, validate_desktop_recipe
from core.manifest import Manifest
from runtime import desktop_launch as launch
from tests.test_desktop_export import app


class IntegrationTests(unittest.TestCase):
    def test_associations_reuse_default_entrypoint_and_reject_ambiguous_handlers(self):
        value = app()
        self.assertEqual(validate_desktop_recipe(Manifest.from_dict(value))['architecture'], 'x86_64')
        value['entrypoints'][0]['executable'] = 'C:/Other.exe'
        with self.assertRaisesRegex(launch.DesktopError, 'identical'):
            validate_desktop_recipe(Manifest.from_dict(value))
        value = app()
        value['fileAssociations'][0]['mime'] = ['text/plain;\nExec=bad']
        with self.assertRaisesRegex(launch.DesktopError, 'MIME'):
            validate_desktop_recipe(Manifest.from_dict(value))

    def test_document_paths_and_local_uris_preserve_arguments(self):
        with tempfile.TemporaryDirectory(prefix='Cage café % ') as td:
            root=Path(td)
            readonly=root/'read only.txt'
            readonly.write_text('original')
            readonly.chmod(0o444)
            new=root/'new document.txt'
            self.assertEqual(launch.document_arguments([readonly.as_uri(), str(new)]),
                             ['Z:'+str(p).replace('/', '\\') for p in (readonly,new)])
            self.assertFalse(new.exists())
            for invalid in (str(root), str(root/'missing-parent/new.txt'), 'https://example.org/a',
                            'file://remote/secret', str(root/'bad\\path.txt')):
                with self.subTest(invalid=invalid), self.assertRaises(launch.DesktopError):
                    launch.document_arguments([invalid])
            self.assertEqual(readonly.read_text(),'original')

    def test_font_payload_is_identical_and_does_not_reference_host_fonts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            platform=root/'platform'
            for family in ('dejavu','liberation-fonts','google-crosextra-carlito','google-crosextra-caladea'):
                path=platform/'share/fonts'/family
                path.mkdir(parents=True)
                (path/'fixture.ttf').write_bytes(family.encode())
            (platform/'share/licenses').mkdir()
            (platform/'share/licenses/notice').write_text('retain pinned component notices')
            for target in ('flatpak','appimage'):
                stage_desktop_fonts(root/target,platform)
            self.assertEqual(launch.inventory_tree(root/'flatpak'),launch.inventory_tree(root/'appimage'))
            self.assertNotIn('/usr/share/fonts',(root/'appimage/share/cage/fonts.conf').read_text())

    def test_desktop_entry_offers_mime_without_default_registration(self):
        plan={'desktop': {'id':'org.example.App','name':'Editor','summary':'Editor','categories':['Utility']},
              'mimeTypes':['text/plain']}
        entry=launch.desktop_entry(plan,'cage-desktop-launch -- %F')
        self.assertIn('MimeType=text/plain;',entry)
        self.assertIn('Exec=cage-desktop-launch -- %F',entry)
        self.assertNotIn('Default',entry)

    def test_dpi_changes_only_display_value_and_honors_existing_custom_preference(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            prefix=root/'prefix'
            prefix.mkdir()
            user=prefix/'user.reg'
            original='[Control Panel\\\\Desktop]\n"LogPixels"=dword:00000060\n\n[Other]\n"setting"="keep"\n'
            user.write_text(original)
            self.assertEqual(launch.prefix_dpi(prefix),96)
            with patch.object(launch,'host_dpi',return_value=192), patch.object(launch,'_run_application',return_value=0) as run:
                launch.configure_display({'display':True},root,prefix,'wine','server',{},None)
                self.assertIn('192',run.call_args.args[0])
                self.assertEqual(user.read_text(),original) # Only reg.exe owns hive mutation.
            user.write_text(original.replace('00000060','00000090'))
            (prefix/'.cage-display.json').unlink()
            with patch.object(launch,'_run_application',return_value=0) as run:
                launch.configure_display({'display':True},root,prefix,'wine','server',{},None)
                self.assertFalse(run.called)
            self.assertEqual(json.loads((root/'display.json').read_text()),{'dpi':144})
            user.write_text(original)
            (root/'display.json').write_text('{"dpi":"preserve"}')
            with patch.object(launch,'_run_application') as run:
                launch.configure_display({'display':True},root,prefix,'wine','server',{},None)
                self.assertFalse(run.called)
            self.assertEqual(user.read_text(),original)

    def test_invalid_display_preferences_and_linked_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for invalid in ([], {'dpi':False},{'dpi':0},{'dpi':385},{'dpi':'huge'},{'dpi':192,'extra':1}):
                (root/'display.json').write_text(json.dumps(invalid))
                with self.assertRaises(launch.DesktopError):
                    launch.display_preferences(root)
            (root/'display.json').unlink()
            (root/'display.json').symlink_to(root/'unrelated')
            with self.assertRaises(launch.DesktopError):
                launch.display_preferences(root)

    def test_explicit_auto_can_replace_custom_dpi_without_resetting_other_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            seed=root/'seed'
            seed.mkdir()
            inventory=[]
            plan={'target':{},'desktop':{'id':'org.example.App'},'layout':{'seed':str(seed)},
                  'seedDigest':launch.digest_json(inventory)}
            metadata=root/'desktop.json'
            metadata.write_text(json.dumps(plan))
            (root/'seed-inventory.json').write_text(json.dumps(inventory))
            state=root/'data/org.example.App'
            prefix=state/'prefix'
            (prefix/'drive_c').mkdir(parents=True)
            (prefix/'user.reg').write_text('[Control Panel\\\\Desktop]\n"LogPixels"=dword:00000090\n')
            identity={'schemaVersion':'cage.desktop-state/v0','seedDigest':'old','runtimeDigest':'old'}
            (prefix/'.cage-state.json').write_text(json.dumps(identity))
            (state/'state.json').write_text(json.dumps(identity))
            (prefix/'drive_c/document').write_text('keep')
            before=(state/'state.json').read_bytes()
            with patch.dict(os.environ,{'XDG_DATA_HOME':str(root/'data')}):
                self.assertEqual(launch.launch(metadata,['--cage-dpi','auto']),0)
            with patch.object(launch,'host_dpi',return_value=192), patch.object(launch,'_run_application',return_value=0) as run:
                launch.configure_display({'display':True},state,prefix,'wine','server',{},None)
                self.assertIn('192',run.call_args.args[0])
            self.assertEqual((state/'state.json').read_bytes(),before)
            self.assertEqual((prefix/'drive_c/document').read_text(),'keep')
