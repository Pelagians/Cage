"""Tests for Cage bundle runtime execution planning."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from artifact.bundle import create_bundle
from core.manifest import Manifest
from runtime.launcher import RunError, build_run_plan


VALID = {
    "schemaVersion": "cage.dev/v0",
    "name": "sample",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "9.0"},
    "dependencies": [{"kind": "winetricks", "verbs": ["corefonts"]}],
    "install": [{
        "kind": "portable",
        "source": "file://app.zip",
        "target": "C:/Program Files/App",
    }],
    "launch": {
        "entrypoint": "C:/Program Files/App/App.exe",
        "args": ["--profile", "default"],
        "env": {"APP_ENV": "test"},
        "workingDirectory": "C:/Program Files/App",
    },
    "provenance": {"sources": []},
}


class Phase3ExecutionPlanTests(unittest.TestCase):

    def _bundle(self, tmp: str) -> Path:
        return create_bundle(Manifest.from_dict(VALID), Path(tmp), dry_run=True)

    def test_build_run_plan_uses_verified_graph_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            plan = build_run_plan(bundle, graphics="headless", engine="podman")

        self.assertEqual(plan["schemaVersion"], "cage.run-plan/v0")
        self.assertEqual(plan["graphics"]["mode"], "headless")
        self.assertEqual(plan["runtime"]["provider"], "wine")
        self.assertEqual(plan["runtime"]["version"], "9.0")
        self.assertEqual(plan["runtime"]["image"], "ghcr.io/pelagians/cage-wine:9.0")
        self.assertEqual(plan["launch"]["entrypoint"], "C:/Program Files/App/App.exe")
        self.assertEqual(plan["container"]["engine"], "podman")
        self.assertIn("/opt/cage/bundle/metadata/graph.json", plan["container"]["environment"]["CAGE_GRAPH"])
        self.assertIn("wine", plan["launchCommand"])
        self.assertIn("--profile", plan["launchCommand"])
        self.assertEqual(plan["verification"]["valid"], True)

    def test_build_run_plan_rejects_invalid_bundle_before_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            (bundle / "metadata" / "graph.json").unlink()
            with self.assertRaises(RunError) as cm:
                build_run_plan(bundle, graphics="headless", engine="podman")

        self.assertIn("missing required file: metadata/graph.json", str(cm.exception))

    def test_build_run_plan_rejects_invalid_graphics_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            with self.assertRaises(RunError) as cm:
                build_run_plan(bundle, graphics="wayland", engine="docker")

        self.assertIn("graphics mode 'wayland' must be one of", str(cm.exception))

    def test_build_run_plan_rejects_invalid_graphics_contract_before_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            graph_path = bundle / "metadata" / "graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["graphics"]["supportedModes"] = ["headless"]
            graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
            with self.assertRaises(RunError) as cm:
                build_run_plan(bundle, graphics="vnc", engine="docker")

        self.assertIn("graph graphics must include defaultMode", str(cm.exception))

    def test_vnc_run_plan_publishes_loopback_vnc_and_novnc_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            plan = build_run_plan(
                bundle,
                graphics="vnc",
                engine="docker",
                network="bridge",
                vnc_port=5901,
                novnc_port=6081,
            )

        argv = plan["container"]["argv"]
        self.assertIn("127.0.0.1:5901:5900", argv)
        self.assertIn("127.0.0.1:6081:6080", argv)
        self.assertIn("x11vnc", plan["container"]["script"])
        self.assertIn("websockify", plan["container"]["script"])

    def test_run_plan_clears_inherited_base_image_dll_overrides_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            plan = build_run_plan(bundle, graphics="headless", engine="docker")

        env = plan["container"]["environment"]
        argv = plan["container"]["argv"]
        self.assertIn("WINEDLLOVERRIDES", env)
        self.assertEqual(env["WINEDLLOVERRIDES"], "")
        self.assertIn("WINEDLLOVERRIDES=", argv)

    def test_wineconsole_entrypoints_use_native_helper_and_strip_legacy_backend_option(self):
        data = dict(VALID)
        data["launch"] = {
            "entrypoint": "C:/windows/system32/wineconsole.exe",
            "args": [
                "--backend=user",
                "C:/windows/system32/WindowsPowerShell/v1.0/powershell.exe",
                "-NoLogo",
                "-NoExit",
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            plan = build_run_plan(bundle, graphics="headless", engine="docker")

        self.assertEqual(
            plan["launchCommand"],
            [
                "wineconsole",
                "C:/windows/system32/WindowsPowerShell/v1.0/powershell.exe",
                "-NoLogo",
                "-NoExit",
            ],
        )

    def test_cli_run_dry_run_prints_run_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            proc = subprocess.run(
                [
                    sys.executable,
                    "cmd/cage.py",
                    "run",
                    "--dry-run",
                    "--graphics",
                    "headless",
                    "--engine",
                    "podman",
                    str(bundle),
                ],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schemaVersion"], "cage.run-plan/v0")
        self.assertEqual(payload["graphics"]["mode"], "headless")
        self.assertEqual(payload["container"]["engine"], "podman")


    def test_umu_proton_ge_run_plan_uses_umu_launcher(self):
        data = dict(VALID)
        data["runtime"] = {"provider": "umu-proton-ge", "version": "GE-Proton9-27"}
        with tempfile.TemporaryDirectory() as tmp:
            bundle = create_bundle(Manifest.from_dict(data), Path(tmp), dry_run=True)
            plan = build_run_plan(bundle, graphics="headless", engine="podman")

        self.assertEqual(plan["runtime"]["provider"], "umu-proton-ge")
        self.assertEqual(plan["runtime"]["launcher"], "umu")
        self.assertEqual(plan["runtime"]["image"], "ghcr.io/pelagians/cage-umu-proton-ge:GE-Proton9-27")
        self.assertIn("umu-run", plan["launchCommand"])


    def test_umu_proton_ge_image_installs_umu_launcher(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "container/runtimes/umu-proton-ge/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("umu-launcher", dockerfile)
        self.assertIn("umu-run", dockerfile)
        self.assertIn("UMU_LAUNCHER_REF", dockerfile)
        self.assertIn("test -x /opt/umu/bin/umu-run", dockerfile)

    def test_runtime_container_images_include_vnc_helpers(self):
        root = Path(__file__).resolve().parents[1]
        dockerfiles = [
            "container/runtimes/wine/Dockerfile",
            "container/runtimes/wine-staging/Dockerfile",
            "container/runtimes/umu-proton-ge/Dockerfile",
        ]
        for rel in dockerfiles:
            with self.subTest(rel=rel):
                dockerfile = (root / rel).read_text(encoding="utf-8")
                self.assertIn("x11vnc", dockerfile)
                self.assertIn("websockify", dockerfile)

    def test_wine_image_contains_powershell_wrapper_build_toolchain(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "container/runtimes/wine/Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python3 git", dockerfile)
        self.assertIn("build-essential", dockerfile)
        self.assertIn("gcc-mingw-w64-x86-64", dockerfile)
        self.assertIn("rustup target add x86_64-pc-windows-gnu", dockerfile)
        self.assertIn("x86_64-w64-mingw32-gcc --version", dockerfile)

    def test_wine_runtime_images_ship_powershell_runtime_smoke(self):
        root = Path(__file__).resolve().parents[1]
        smoke = (root / "container/common/cage-powershell-runtime-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("PowerShell-7.5.5-win-x64.msi", smoke)
        self.assertIn("b2ac56b7639e2b259bb78bab077555d76f2a5eec6c516690d63de36bc1d6ca25", smoke)
        self.assertIn("PWSH-ALIVE", smoke)
        self.assertIn("cage-pwsh-smoke-ok.txt", smoke)
        self.assertIn("try_pwsh_launch direct", smoke)
        self.assertIn("try_pwsh_launch cmd", smoke)
        self.assertIn("POWER SHELL RUNTIME SMOKE PASSED", smoke)
        self.assertIn('export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-mscoree,mshtml=}"', smoke)
        self.assertIn("wine wineboot --init", smoke)
        self.assertIn('export WINEDLLOVERRIDES=""', smoke)
        self.assertLess(
            smoke.index("wine wineboot --init"),
            smoke.index('export WINEDLLOVERRIDES=""'),
        )
        self.assertNotIn("unset WINEDLLOVERRIDES", smoke)
        for rel in [
            "container/runtimes/wine/Dockerfile",
            "container/runtimes/wine-staging/Dockerfile",
        ]:
            with self.subTest(rel=rel):
                dockerfile = (root / rel).read_text(encoding="utf-8")
                self.assertIn("cage-powershell-runtime-smoke.sh", dockerfile)
                self.assertIn("/usr/local/bin/cage-powershell-runtime-smoke", dockerfile)

    def test_container_workflow_smokes_powershell_on_published_wine_11_image(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/containers.yml").read_text(encoding="utf-8")

        self.assertIn("Smoke PowerShell runtime on wine 11.0", workflow)
        self.assertIn("matrix.provider == 'wine' && matrix.version == '11.0'", workflow)
        self.assertIn("github.sha", workflow)
        self.assertIn("cage-powershell-runtime-smoke", workflow)
        self.assertIn("--shm-size 2g", workflow)


if __name__ == "__main__":
    unittest.main()
