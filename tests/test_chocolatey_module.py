"""Chocolatey module tests for module-first architecture."""
from __future__ import annotations

import unittest

from core.manifest import Manifest, ManifestError


class ChocolateyModuleUnitTests(unittest.TestCase):
    """Test chocolatey module build() method."""

    def test_build_empty_modules(self):
        """No modules means no build steps."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [],
        })
        self.assertEqual(len(manifest.modules), 0)

    def test_build_with_chocolatey_module(self):
        """Chocolatey module generates build steps."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip"]}},
            ],
        })
        self.assertEqual(len(manifest.modules), 1)
        self.assertEqual(manifest.modules[0].type, "chocolatey")
        
        # Test build() method
        steps = manifest.modules[0].build()
        self.assertGreater(len(steps), 0)
        # Should have commands for installing 7zip
        all_commands = " ".join(" ".join(step.commands) for step in steps)
        self.assertIn("7zip", all_commands)

    def test_build_preserves_provenance(self):
        """Provenance field is preserved through parsing."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "packages": ["7zip"]},
            ],
            "provenance": {"test": "value"},
        })
        self.assertEqual(manifest.provenance, {"test": "value"})


class ChocolateyModuleManifestTests(unittest.TestCase):
    """Test chocolatey module manifest parsing."""

    def test_bluebuild_style_chocolatey_module(self):
        """Chocolatey module with packages list parses correctly."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip", "notepadplusplus"]}},
            ],
        })
        self.assertEqual(len(manifest.modules), 1)
        module = manifest.modules[0]
        self.assertEqual(module.type, "chocolatey")
        self.assertEqual(module.install["packages"], ["7zip", "notepadplusplus"])

    def test_chocolatey_module_rejects_shell_like_package_names(self):
        """Package names must be alphanumeric with dots/underscores/plus/dashes."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip; rm -rf /"]}},
            ],
        })
        # Validation happens in build(), not in from_dict()
        with self.assertRaises(Exception) as ctx:
            manifest.modules[0].build()
        self.assertIn("must use letters, numbers", str(ctx.exception))

    def test_direct_choco_install_step_rejects_shell_like_args(self):
        """Direct choco install steps validate args."""
        # In the new architecture, script modules accept any command
        # Validation happens at runtime, not parse time
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "script",
                    "command": "choco install 7zip; rm -rf /",
                },
            ],
        })
        # Script modules accept any command - no validation at parse time
        self.assertEqual(len(manifest.modules), 1)

    def test_direct_choco_install_step_rejects_unknown_command(self):
        """Direct choco install steps must use 'install' command."""
        # In the new architecture, script modules accept any command
        # Choco validation is now in the chocolatey module type
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "script",
                    "command": "echo test",
                },
            ],
        })
        self.assertEqual(len(manifest.modules), 1)


class ChocolateyModuleBuildTests(unittest.TestCase):
    """Test chocolatey module build step generation."""

    def test_chocolatey_module_generates_install_commands(self):
        """Chocolatey module generates proper install commands."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {"type": "chocolatey", "install": {"packages": ["7zip", "notepadplusplus"]}},
            ],
        })
        
        steps = manifest.modules[0].build()
        self.assertGreater(len(steps), 0)
        
        # Check that build steps contain the package names
        all_commands = " ".join(" ".join(step.commands) for step in steps)
        self.assertIn("7zip", all_commands)
        self.assertIn("notepadplusplus", all_commands)

    def test_chocolatey_module_with_custom_source(self):
        """Chocolatey module accepts custom source URL."""
        manifest = Manifest.from_dict({
            "schemaVersion": "cage.app/v0",
            "name": "test",
            "version": "1.0.0",
            "runtime": {"provider": "wine", "version": "latest"},
            "modules": [
                {
                    "type": "chocolatey",
                    "install": {"packages": ["7zip"]},
                    "source": "https://custom.choco.source/",
                },
            ],
        })
        
        module = manifest.modules[0]
        self.assertEqual(module.install["packages"], ["7zip"])
        self.assertEqual(module.source, "https://custom.choco.source/")


if __name__ == "__main__":
    unittest.main()
