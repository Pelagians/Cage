import unittest
from pathlib import Path

from builder.pipeline import generate_build_script
from core.manifest import load_manifest


class ChocolateyForWineRecipeTests(unittest.TestCase):
    def test_sandbox_recipe_uses_chocolatey_for_wine_release_without_rust_wrapper(self):
        recipe = Path("recipes/chocolatey-for-wine-sandbox.winforge.yaml")
        manifest = load_manifest(recipe)

        self.assertEqual(manifest.name, "chocolatey-for-wine-sandbox")
        self.assertEqual(manifest.runtime.provider, "wine")
        self.assertEqual(manifest.runtime.version, "latest")
        self.assertEqual(manifest.runtime.network, "bridge")
        self.assertEqual(manifest.launch.entrypoint, "C:/windows/system32/wineconsole.exe")
        self.assertIn("C:/windows/system32/WindowsPowerShell/v1.0/powershell.exe", manifest.launch.args)
        self.assertEqual(manifest.launch.env.get("ChocolateyInstall"), "C:\\ProgramData\\chocolatey")

        script = generate_build_script(manifest)
        self.assertIn("Chocolatey-for-wine/releases/download/v0.5c.755/Chocolatey-for-wine.7z", script)
        self.assertIn("87f4ecc08a9b22f16aa5633ca107c151ddf3fed0b256fed9fb99680af7095d14", script)
        self.assertIn("sha256sum -c -", script)
        self.assertIn("7z x -y", script)
        self.assertIn("ChoCinstaller_*.exe", script)
        self.assertIn("/q", script)
        self.assertIn("choc_install.ps1", script)
        self.assertIn("winepath -w", script)
        self.assertIn("Chocolatey-for-wine installer returned without choco.exe", script)
        self.assertIn("Normalizing ChocolateyInstall payload path", script)
        self.assertIn("-iname chocolateyInstall", script)
        self.assertIn("-iname pwsh.exe", script)
        self.assertIn("minimal Chocolatey payload fallback", script)
        self.assertIn("choco.exe --version", script)
        self.assertIn("wine reg add", script)
        self.assertIn("C:\\ProgramData\\chocolatey", script)
        self.assertIn("$choco_root/choco.exe", script)
        self.assertIn("bin/choco.exe launcher failed", script)
        self.assertIn("feature disable --name=powershellHost", script)
        self.assertIn("feature enable -n allowGlobalConfirmation", script)
        self.assertNotIn("powershell-wrapper-for-wine", script)
        self.assertNotIn("cargo", script)
        self.assertNotIn("rustup", script)


if __name__ == "__main__":
    unittest.main()
