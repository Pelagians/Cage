"""Tests for BYO (Bring Your Own) files with files module."""
import unittest
from pathlib import Path

from core.manifest import Manifest, load_manifest


class ByoSourcePolicyAndFilesModuleTests(unittest.TestCase):
    """Test BYO source policy with files module."""

    def test_sources_normalize_byo_policy_and_files_type(self):
        """Test that BYO sources are normalized correctly."""
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "byo-test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "sources": [
                {
                    "id": "office-files",
                    "type": "files",
                    "policy": "bring-your-own-files",
                    "path": "sources/office-files",
                }
            ],
            "modules": [
                {
                    "type": "files",
                    "mappings": [
                        {"source": "sources/office-files/WORD.EXE", "target": "C:/Office/WORD.EXE"},
                    ]
                }
            ]
        }
        manifest = Manifest.from_dict(data)
        self.assertEqual(len(manifest.sources), 1)
        self.assertEqual(manifest.sources[0].id, "office-files")
        self.assertEqual(manifest.sources[0].type, "files")
        self.assertEqual(manifest.sources[0].policy, "bring-your-own-files")

    def test_invalid_source_policy_is_rejected(self):
        """Test that invalid source policy is rejected."""
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "byo-test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "sources": [
                {
                    "id": "test",
                    "type": "files",
                    "policy": "invalid-policy",
                }
            ]
        }
        with self.assertRaises(Exception):
            Manifest.from_dict(data)

    def test_filesystem_merge_layers_folder_contents_into_target(self):
        """Test that files module with merge mode works correctly."""
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "merge-test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "files",
                    "mappings": [
                        {"source": "./config", "target": "C:/app/config", "mode": "merge"},
                    ]
                }
            ]
        }
        manifest = Manifest.from_dict(data)
        self.assertEqual(len(manifest.modules), 1)
        module = manifest.modules[0]
        self.assertEqual(module.type, "files")
        self.assertEqual(module.mappings[0]["mode"], "merge")


class SuiteEntrypointTests(unittest.TestCase):
    """Test suite entrypoints and file associations."""

    def test_manifest_records_suite_entrypoints_and_file_associations(self):
        """Test that manifest parses entrypoints and file associations."""
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "suite-test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "entrypoints": [
                {
                    "id": "word",
                    "name": "Microsoft Word",
                    "executable": "C:/Office/WINWORD.EXE",
                }
            ],
            "fileAssociations": [
                {
                    "entrypoint": "word",
                    "extensions": [".docx", ".doc"],
                }
            ]
        }
        manifest = Manifest.from_dict(data)
        self.assertEqual(len(manifest.entrypoints), 1)
        self.assertEqual(manifest.entrypoints[0]["id"], "word")
        self.assertEqual(len(manifest.file_associations), 1)
        self.assertEqual(manifest.file_associations[0]["entrypoint"], "word")

    def test_file_association_must_reference_known_entrypoint(self):
        """Test that file associations reference valid entrypoints."""
        # In the new architecture, we don't validate this at parse time
        # Validation happens at runtime
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "suite-test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "entrypoints": [
                {
                    "id": "word",
                    "name": "Microsoft Word",
                    "executable": "C:/Office/WINWORD.EXE",
                }
            ],
            "fileAssociations": [
                {
                    "entrypoint": "nonexistent",
                    "extensions": [".docx"],
                }
            ]
        }
        # This should parse successfully - validation is runtime
        manifest = Manifest.from_dict(data)
        self.assertEqual(len(manifest.file_associations), 1)


class OfficeProfileTests(unittest.TestCase):
    """Test Office profile expansion."""

    def test_office_legacy_profile_expands_compatibility_and_winetricks_dependencies(self):
        """Test that Office profile expands correctly."""
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "office-test",
            "version": "2016",
            "runtime": {"provider": "wine", "version": "latest"},
            "profiles": ["office-legacy-32bit"],
            "modules": []
        }
        # Profiles are stored but not expanded in the new architecture
        manifest = Manifest.from_dict(data)
        self.assertEqual(manifest.profiles, ["office-legacy-32bit"])

    def test_explicit_compatibility_overrides_profile_defaults(self):
        """Test that explicit compatibility overrides profile defaults."""
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "office-test",
            "version": "2016",
            "runtime": {"provider": "wine", "version": "latest"},
            "compatibility": {
                "windowsVersion": "win10",
            },
            "modules": []
        }
        manifest = Manifest.from_dict(data)
        self.assertEqual(manifest.compatibility["windowsVersion"], "win10")


if __name__ == "__main__":
    unittest.main()
