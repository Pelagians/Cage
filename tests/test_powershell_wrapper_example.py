from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.manifest import load_manifest


class PowershellWrapperExampleTests(unittest.TestCase):
    def test_powershell_wrapper_example_loads_builds_and_plans_vnc_launch(self):
        repo = Path(__file__).resolve().parents[1]
        recipe = repo / "examples" / "powershell-wrapper-pwsh-vnc.cage.yaml"
        manifest = load_manifest(recipe)

        self.assertEqual(manifest.name, "powershell-wrapper-pwsh-vnc")
        self.assertEqual([m.type for m in manifest.modules], ["powershell-wrapper"])
        self.assertEqual(manifest.runtime.provider, "wine")
        self.assertEqual(manifest.runtime.version, "latest")
        self.assertEqual(manifest.runtime.network, "bridge")
        self.assertEqual(manifest.launch.entrypoint, "C:/windows/system32/wineconsole.exe")
        self.assertIn("C:/windows/system32/WindowsPowerShell/v1.0/powershell.exe", manifest.launch.args)
        self.assertEqual(manifest.launch.env.get("VNC_GEOMETRY"), "1920x1080")

    @unittest.skip("Requires Docker daemon")
    def test_powershell_wrapper_example_builds_and_inspects(self):
        repo = Path(__file__).resolve().parents[1]
        recipe = repo / "examples" / "powershell-wrapper-pwsh-vnc.cage.yaml"
        
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dist"
            build_proc = subprocess.run(
                [
                    sys.executable,
                    "cmd/cage.py",
                    "build",
                    str(recipe),
                    "--output",
                    str(out),
                ],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build_proc.returncode, 0, build_proc.stderr)

            bundles = sorted(out.glob("*.tar"))
            self.assertEqual(len(bundles), 1)
            bundle = bundles[0]
            self.assertTrue(bundle.name.startswith("powershell-wrapper-pwsh-vnc-"))

            inspect_proc = subprocess.run(
                [
                    sys.executable,
                    "cmd/cage.py",
                    "inspect",
                    str(bundle),
                ],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(inspect_proc.returncode, 0, inspect_proc.stderr)

            summary = json.loads(inspect_proc.stdout)
            self.assertEqual(summary["application"]["name"], "powershell-wrapper-pwsh-vnc")
            self.assertEqual(summary["runtime"]["runner"]["network"], "bridge")
            self.assertEqual(summary["launch"]["entrypoint"], "C:/windows/system32/wineconsole.exe")
            self.assertIn("C:/windows/system32/WindowsPowerShell/v1.0/powershell.exe", summary["launch"]["args"])
            self.assertEqual(summary["launch"]["env"].get("VNC_GEOMETRY"), "1920x1080")
            self.assertEqual(summary["graph"]["application"]["name"], "powershell-wrapper-pwsh-vnc")


if __name__ == "__main__":
    unittest.main()
