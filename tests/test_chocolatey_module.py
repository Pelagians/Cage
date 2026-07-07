from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from builder.pipeline import generate_build_script
from core.manifest import Manifest, ManifestError, load_manifest


def _module_manifest() -> dict[str, object]:
    return {
        "schemaVersion": "cage.app/v0",
        "name": "choco-demo",
        "version": "1.0.0",
        "runtime": {"provider": "wine", "version": "latest"},
        "modules": [
            {
                "type": "chocolatey",
                "install": {
                    "packages": ["firefox", "7zip.install"],
                },
            }
        ],
        "launch": {"entrypoint": "C:/Program Files/Mozilla Firefox/firefox.exe"},
    }



class ChocolateyModuleUnitTests(unittest.TestCase):
    """Standalone unit tests for module expansion not mediated by Manifest.from_dict."""

    def test_apply_modules_empty(self):
        from core.modules import apply_modules
        result = apply_modules({"schemaVersion": "cage.app/v0"})
        self.assertNotIn("provenance", result)

    def test_apply_modules_preserves_existing_provenance(self):
        from core.modules import apply_modules
        data = {
            "schemaVersion": "cage.app/v0",
            "modules": [{"type": "chocolatey", "install": {"packages": ["firefox"]}}],
            "provenance": {"builtBy": "test"}
        }
        result = apply_modules(data)
        self.assertEqual(result["provenance"]["builtBy"], "test")
        self.assertIn("moduleExpansions", result["provenance"])

    def test_modulespec_round_trip(self):
        from core.modules import parse_module
        orig = parse_module({"type": "chocolatey", "install": {"packages": ["firefox", "7zip.install"]}}, 0)
        self.assertEqual(orig.type, "chocolatey")
        self.assertEqual(orig.install, {"packages": ["firefox", "7zip.install"]})
        # Note: to_dict() no longer exists in the new module system
        # Modules are now typed dataclasses, not dict-based

class ChocolateyModuleManifestTests(unittest.TestCase):
    def test_bluebuild_style_chocolatey_module_expands_to_dependencies_and_install_steps(self):
        manifest = Manifest.from_dict(_module_manifest())

        # Should have both powershell and chocolatey modules (powershell auto-injected)
        self.assertEqual([module.type for module in manifest.modules], ["powershell", "chocolatey"])
        self.assertEqual(manifest.modules[1].install["packages"], ["firefox", "7zip.install"])
        
        # Check winetricks dependencies (powershell provides powershell_core+win10, chocolatey provides dotnet48)
        winetricks = [dep for dep in manifest.dependencies if dep.kind == "winetricks"]
        self.assertEqual(len(winetricks), 2)
        
        # Find the powershell module's winetricks (should have powershell_core and win10)
        powershell_winetricks = [w for w in winetricks if "powershell_core" in w.verbs]
        self.assertTrue(powershell_winetricks)
        self.assertIn("powershell_core", powershell_winetricks[0].verbs)
        self.assertIn("win10", powershell_winetricks[0].verbs)
        
        # Find the chocolatey module's winetricks (should have dotnet48)
        chocolatey_winetricks = [w for w in winetricks if "dotnet48" in w.verbs]
        self.assertTrue(chocolatey_winetricks)
        self.assertIn("dotnet48", chocolatey_winetricks[0].verbs)
        
        # Check install steps (powershell setup + choco installs)
        # Powershell module should have setup scripts, chocolatey should have choco install steps
        choco_steps = [step for step in manifest.install if step.kind == "choco"]
        self.assertEqual(len(choco_steps), 2)
        self.assertEqual(choco_steps[0].command, "install")
        self.assertEqual(choco_steps[0].args, ["firefox", "-y", "--no-progress"])
        self.assertEqual(choco_steps[1].args, ["7zip.install", "-y", "--no-progress"])
        
        # Check provenance tracking
        self.assertEqual(manifest.provenance["moduleExpansions"][0]["type"], "powershell")
        self.assertEqual(manifest.provenance["moduleExpansions"][1]["type"], "chocolatey")

    def test_strict_yaml_accepts_myos_bluebuild_style_modules_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp) / "choco-demo.cage.yaml"
            recipe.write_text(
                """schemaVersion: cage.app/v0
name: choco-demo
version: 1.0.0
runtime:
  provider: wine
  version: latest
modules:
  - type: chocolatey
    install:
      packages:
        - firefox
        - 7zip.install
launch:
  entrypoint: C:/Program Files/Mozilla Firefox/firefox.exe
""",
                encoding="utf-8",
            )
            manifest = load_manifest(recipe)

        self.assertEqual(len(manifest.modules), 2)
        self.assertEqual(manifest.modules[0].type, "powershell")
        self.assertEqual(manifest.modules[1].type, "chocolatey")
        self.assertEqual(manifest.modules[1].install["packages"], ["firefox", "7zip.install"])


    def test_public_chocolatey_example_uses_modules_shape(self):
        manifest = load_manifest(Path("examples/chocolatey-firefox.cage.yaml"))

        self.assertEqual(len(manifest.modules), 2)
        self.assertEqual(manifest.modules[0].type, "powershell")
        self.assertEqual(manifest.modules[1].type, "chocolatey")
        self.assertEqual(manifest.modules[1].install["packages"], ["firefox"])
        # PowerShell module injects 8 script steps:
        # 1. Download wrapper
        # 2. Copy wrapper to system32
        # 3. Install Chocolatey (PietJankbal's script)
        # 4-8. Build mode steps (install deps, build, copy, cleanup, remove deps)
        # Then chocolatey adds the choco install step at index 8
        self.assertEqual(manifest.install[8].kind, "choco")
        self.assertEqual(manifest.install[8].args, ["firefox", "-y", "--no-progress"])

    def test_chocolatey_module_rejects_shell_like_package_names(self):
        data = _module_manifest()
        data["modules"][0]["install"]["packages"] = ["firefox;touch-/tmp/no"]

        # After auto-injection, chocolatey is at index 1 (powershell is at 0)
        with self.assertRaisesRegex(ManifestError, r"modules\[1\]\.install\.packages\[0\]"):
            Manifest.from_dict(data)


    def test_direct_choco_install_step_requires_install_command_and_args(self):
        data = _module_manifest()
        data.pop("modules")
        data["install"] = [{"kind": "choco"}]

        with self.assertRaisesRegex(ManifestError, r"install\[0\]\.command"):
            Manifest.from_dict(data)

    def test_direct_choco_install_step_rejects_unknown_command(self):
        data = _module_manifest()
        data.pop("modules")
        data["install"] = [{"kind": "choco", "command": "upgrade", "args": ["firefox"]}]

        with self.assertRaisesRegex(ManifestError, r"install\[0\]\.command"):
            Manifest.from_dict(data)


    def test_direct_choco_install_step_rejects_shell_like_args(self):
        data = _module_manifest()
        data.pop("modules")
        data["install"] = [{"kind": "choco", "command": "install", "args": ["firefox;touch-/tmp/no"]}]

        with self.assertRaisesRegex(ManifestError, r"install\[0\]\.args\[0\]"):
            Manifest.from_dict(data)

    def test_unknown_module_type_is_rejected(self):
        data = _module_manifest()
        data["modules"][0]["type"] = "dnf"

        with self.assertRaisesRegex(ManifestError, r"modules\[0\]\.type"):
            Manifest.from_dict(data)


class ChocolateyModuleBuildScriptTests(unittest.TestCase):
    def test_chocolatey_module_generates_setup_before_package_installs(self):
        manifest = Manifest.from_dict(_module_manifest())
        script = generate_build_script(manifest)

        # PowerShell wrapper setup should come before choco installs
        setup_index = script.index("powershell-wrapper")
        choco_index = script.index("choco @chocoArgs")
        self.assertLess(setup_index, choco_index)
        zip_index = script.index("Running Chocolatey command: install 7zip.install -y --no-progress")
        firefox_index = script.index("Running Chocolatey command: install firefox -y --no-progress")
        self.assertLess(setup_index, firefox_index)
        self.assertLess(firefox_index, zip_index)
        self.assertIn('wine "$WINEPREFIX/drive_c/Program Files/PowerShell/7/pwsh.exe"', script)
        self.assertIn("$chocoArgs = @(", script)
        self.assertIn("& choco @chocoArgs", script)
        self.assertNotIn("eval choco", script)
        self.assertNotIn('echo "  Running custom script command: set -eu;', script)


if __name__ == "__main__":
    unittest.main()
