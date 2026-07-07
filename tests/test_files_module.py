"""Tests for files module build() method."""
import unittest
from pathlib import Path

from core.manifest import Manifest, load_manifest
from core.modules import parse_module, FilesModule, ModuleError


class FilesModuleUnitTests(unittest.TestCase):
    """Unit tests for files module parsing and build()."""

    def test_parse_files_module(self):
        """Test parsing a files module definition."""
        module = parse_module({
            "type": "files",
            "mappings": [
                {"source": "./config", "target": "C:/app/config"},
                {"source": "./data", "target": "C:/app/data", "mode": "merge"},
            ]
        }, 0)
        
        self.assertIsInstance(module, FilesModule)
        self.assertEqual(module.type, "files")
        self.assertEqual(len(module.mappings), 2)
        self.assertEqual(module.mappings[0]["source"], "./config")
        self.assertEqual(module.mappings[0]["target"], "C:/app/config")
        self.assertEqual(module.mappings[1]["mode"], "merge")

    def test_files_module_requires_mappings(self):
        """Test that files module requires mappings field."""
        module = FilesModule(type="files", mappings=None)
        with self.assertRaises(ModuleError) as ctx:
            module.build()
        self.assertIn("mappings", str(ctx.exception))

    def test_files_module_mapping_requires_source(self):
        """Test that each mapping requires source field."""
        module = FilesModule(
            type="files",
            mappings=[{"target": "C:/app/config"}]
        )
        with self.assertRaises(ModuleError) as ctx:
            module.build()
        self.assertIn("source", str(ctx.exception))

    def test_files_module_mapping_requires_target(self):
        """Test that each mapping requires target field."""
        module = FilesModule(
            type="files",
            mappings=[{"source": "./config"}]
        )
        with self.assertRaises(ModuleError) as ctx:
            module.build()
        self.assertIn("target", str(ctx.exception))

    def test_files_module_build_generates_commands(self):
        """Test that files module generates copy commands."""
        module = FilesModule(
            type="files",
            mappings=[
                {"source": "./config", "target": "C:/app/config"},
                {"source": "./data", "target": "C:/app/data", "mode": "merge"},
            ]
        )
        steps = module.build()
        
        self.assertGreater(len(steps), 0)
        # Check that build steps contain copy commands
        all_commands = " ".join(" ".join(step.commands) for step in steps)
        self.assertIn("config", all_commands)
        self.assertIn("data", all_commands)


class FilesModuleManifestTests(unittest.TestCase):
    """Integration tests for files module in full manifest."""

    def test_files_module_in_manifest(self):
        """Test that files module works in a full manifest."""
        data = {
            "schemaVersion": "cage.app/v0",
            "name": "files-test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "files",
                    "mappings": [
                        {"source": "./config", "target": "C:/app/config"},
                    ]
                }
            ]
        }
        manifest = Manifest.from_dict(data)
        self.assertEqual(len(manifest.modules), 1)
        self.assertEqual(manifest.modules[0].type, "files")
        
        # Test build() method
        steps = manifest.modules[0].build()
        self.assertGreater(len(steps), 0)


if __name__ == "__main__":
    unittest.main()
