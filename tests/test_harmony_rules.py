import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('harmony_rules',ROOT/'packaging/myharmony/manage-usb-rules.py')
rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)


class HarmonyRulesTests(unittest.TestCase):
    def test_shared_ownership_modified_file_preservation_and_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=ROOT/'packaging/myharmony/70-cage-myharmony.rules'
            target=root/'etc/udev/rules.d/70-cage-myharmony.rules'
            self.assertTrue(rules.apply(root,source,'org.example.First')['changed'])
            self.assertFalse(rules.apply(root,source,'org.example.Second')['changed'])
            result=rules.apply(root,source,'org.example.First',remove=True)
            self.assertTrue(target.exists());self.assertEqual(result['owners'],['org.example.Second'])
            original=target.read_bytes();target.write_bytes(original+b'# administrator edit\n')
            with self.assertRaisesRegex(ValueError,'modified'):rules.apply(root,source,'org.example.Second',remove=True)
            self.assertEqual(target.read_bytes(),original+b'# administrator edit\n')
            target.write_bytes(original)
            result=rules.apply(root,source,'org.example.Second',remove=True)
            self.assertFalse(target.exists())
            self.assertEqual((Path(result['recoveryDirectory'])/(rules.sha(source)+'.rules')).read_bytes(),original)
            self.assertFalse(rules.apply(root,source,'org.example.Second',remove=True)['changed'])

    def test_identical_untracked_rules_are_never_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=ROOT/'packaging/myharmony/70-cage-myharmony.rules'
            target=root/'etc/udev/rules.d/70-cage-myharmony.rules';target.parent.mkdir(parents=True);target.write_bytes(source.read_bytes())
            rules.apply(root,source,'org.example.First')
            rules.apply(root,source,'org.example.First',remove=True)
            self.assertTrue(target.exists())

    def test_untracked_modified_rules_and_links_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=ROOT/'packaging/myharmony/70-cage-myharmony.rules'
            target=root/'etc/udev/rules.d/70-cage-myharmony.rules';target.parent.mkdir(parents=True);target.write_text('custom')
            with self.assertRaisesRegex(ValueError,'untracked'):rules.apply(root,source,'org.example.First')
            self.assertEqual(target.read_text(),'custom')
            target.unlink();target.symlink_to(source)
            with self.assertRaisesRegex(ValueError,'linked'):rules.apply(root,source,'org.example.First')


if __name__=='__main__':unittest.main()
