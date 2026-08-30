"""Tests for Cage bundle runtime execution planning."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact.bundle import create_bundle
from core.manifest import Manifest
from runtime.launcher import RunError, build_run_plan, execute_run_plan

VALID = {
    "schemaVersion": "cage.app/v0",
    "name": "sample",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "9.0"},
    "modules": [
        {"type": "winetricks", "verbs": ["corefonts"]},
        {
            "type": "portable",
            "source": "file://app.zip",
            "target": "C:/Program Files/App",
        },
    ],
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
            plan = build_run_plan(
                bundle, graphics="headless", engine="podman", allow_non_runnable=True
            )

        self.assertEqual(plan["schemaVersion"], "cage.run-plan/v0")
        self.assertEqual(plan["graphics"]["mode"], "headless")
        self.assertEqual(plan["runtime"]["provider"], "wine")
        self.assertEqual(plan["runtime"]["version"], "9.0")
        self.assertEqual(plan["runtime"]["image"], "ghcr.io/pelagians/cage-wine:9.0")
        self.assertEqual(plan["launch"]["entrypoint"], "C:/Program Files/App/App.exe")
        self.assertEqual(plan["container"]["engine"], "podman")
        self.assertEqual(
            plan["container"]["argv"][3:6],
            ["--userns=keep-id", "--user", "0:0"],
        )
        self.assertEqual(plan["container"]["environment"]["PUID"], str(os.getuid()))
        self.assertEqual(plan["container"]["environment"]["PGID"], str(os.getgid()))
        self.assertIn(
            "/opt/cage/bundle/metadata/graph.json",
            plan["container"]["environment"]["CAGE_GRAPH"],
        )
        self.assertIn("wine", plan["launchCommand"])
        self.assertIn("--profile", plan["launchCommand"])
        self.assertEqual(plan["verification"]["valid"], True)

    def test_build_run_plan_rejects_invalid_bundle_before_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            (bundle / "metadata" / "graph.json").unlink()
            with self.assertRaises(RunError) as cm:
                build_run_plan(
                    bundle,
                    graphics="headless",
                    engine="podman",
                    allow_non_runnable=True,
                )

        self.assertIn("missing required file: metadata/graph.json", str(cm.exception))

    def test_build_run_plan_rejects_structurally_valid_non_runnable_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)

            with self.assertRaises(RunError) as cm:
                build_run_plan(bundle, graphics="headless", engine="podman")

        message = str(cm.exception)
        self.assertIn("not runnable", message)
        self.assertIn("dry-run-placeholder", message)
        self.assertIn("state=planned", message)

    def test_docker_run_plan_preserves_identity_without_podman_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_run_plan(
                self._bundle(tmp),
                graphics="headless",
                engine="docker",
                allow_non_runnable=True,
            )

        argv = plan["container"]["argv"]
        self.assertNotIn("--userns=keep-id", argv)
        self.assertNotIn("--user", argv)
        self.assertEqual(plan["container"]["environment"]["PUID"], str(os.getuid()))
        self.assertEqual(plan["container"]["environment"]["PGID"], str(os.getgid()))

    def test_docker_emulation_run_plan_uses_podman_identity(self):
        class Version:
            stdout = "podman version 5.4.2"

        with tempfile.TemporaryDirectory() as tmp, patch(
            "container.manager.shutil.which", return_value="/usr/bin/docker"
        ), patch("container.manager.subprocess.run", return_value=Version()):
            plan = build_run_plan(
                self._bundle(tmp),
                graphics="headless",
                engine="docker",
                allow_non_runnable=True,
            )

        self.assertEqual(plan["container"]["engine"], "podman")
        self.assertEqual(
            plan["container"]["argv"][3:6],
            ["--userns=keep-id", "--user", "0:0"],
        )
        self.assertEqual(plan["container"]["environment"]["PUID"], str(os.getuid()))
        self.assertEqual(plan["container"]["environment"]["PGID"], str(os.getgid()))

    def test_timeout_bytes_are_returned_as_json_serializable_text(self):
        plan = {
            "bundle": "/tmp/example",
            "graphics": {"mode": "selkies"},
            "runtime": {"image": "example@sha256:" + "a" * 64},
            "container": {"argv": ["podman", "run", "example"]},
        }
        timeout = subprocess.TimeoutExpired(
            plan["container"]["argv"],
            5,
            output=b"partial stdout\xff",
            stderr=b"partial stderr\xfe",
        )

        with patch("runtime.launcher.subprocess.run", side_effect=timeout):
            result = execute_run_plan(plan, timeout=5)

        self.assertEqual(result["stdout"], "partial stdout\ufffd")
        self.assertEqual(result["stderr"], "partial stderr\ufffd")
        json.dumps(result)

    def test_build_run_plan_rejects_invalid_graphics_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            with self.assertRaises(RunError) as cm:
                build_run_plan(
                    bundle, graphics="wayland", engine="docker", allow_non_runnable=True
                )

        self.assertIn("graphics mode 'wayland' must be one of", str(cm.exception))

    def test_build_run_plan_rejects_invalid_graphics_contract_before_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            graph_path = bundle / "metadata" / "graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["graphics"]["supportedModes"] = ["headless"]
            graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
            with self.assertRaises(RunError) as cm:
                build_run_plan(
                    bundle, graphics="selkies", engine="docker", allow_non_runnable=True
                )

        self.assertIn("graph graphics must include defaultMode", str(cm.exception))

    def test_selkies_run_plan_publishes_loopback_https_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            plan = build_run_plan(
                bundle,
                graphics="selkies",
                engine="docker",
                network="bridge",
                selkies_port=3002,
                allow_non_runnable=True,
            )

        argv = plan["container"]["argv"]
        self.assertIn("127.0.0.1:3002:3001", argv)
        self.assertNotIn("5900", " ".join(argv))
        self.assertNotIn("6080", " ".join(argv))
        self.assertEqual(argv[-1], plan["runtime"]["image"])

    def test_run_plan_inherits_producer_image_dll_policy_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            plan = build_run_plan(
                bundle, graphics="headless", engine="docker", allow_non_runnable=True
            )

        env = plan["container"]["environment"]
        argv = plan["container"]["argv"]
        self.assertNotIn("WINEDLLOVERRIDES", env)
        self.assertFalse(any(value.startswith("WINEDLLOVERRIDES=") for value in argv))

    def test_wineconsole_entrypoints_use_native_helper_and_strip_legacy_backend_option(
        self,
    ):
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
            plan = build_run_plan(
                bundle, graphics="headless", engine="docker", allow_non_runnable=True
            )

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
            plan = build_run_plan(
                bundle, graphics="headless", engine="podman", allow_non_runnable=True
            )

        self.assertEqual(plan["runtime"]["provider"], "umu-proton-ge")
        self.assertEqual(plan["runtime"]["launcher"], "umu")
        self.assertEqual(
            plan["runtime"]["image"],
            "ghcr.io/pelagians/cage-umu-proton-ge:GE-Proton9-27",
        )
        self.assertIn("umu-run", plan["launchCommand"])

    def test_runtime_container_images_use_selkies_without_legacy_vnc_helpers(self):
        root = Path(__file__).resolve().parents[1]
        dockerfiles = [
            "container/runtimes/wine/Dockerfile",
            "container/runtimes/wine-staging/Dockerfile",
            "container/runtimes/umu-proton-ge/Dockerfile",
        ]
        for rel in dockerfiles:
            with self.subTest(rel=rel):
                dockerfile = (root / rel).read_text(encoding="utf-8").lower()
                self.assertIn("baseimage-selkies", dockerfile)
                self.assertIn("pixelflux", dockerfile)
                self.assertIn("expose 3001", dockerfile)
                for obsolete in ("x11vnc", "websockify", "novnc", "xvfb"):
                    self.assertNotIn(obsolete, dockerfile)

    def test_builder_maps_abc_to_the_host_user_for_bundle_writes(self):
        root = Path(__file__).resolve().parents[1]
        executor = (root / "builder/executor.py").read_text(encoding="utf-8")
        self.assertIn('"PUID": str(os.getuid())', executor)
        self.assertIn('"PGID": str(os.getgid())', executor)

    def test_builder_uses_universal_selkies_init_instead_of_image_command(self):
        root = Path(__file__).resolve().parents[1]
        executor = (root / "builder/executor.py").read_text(encoding="utf-8")
        self.assertIn("CAGE_BUILD_SCRIPT_B64", executor)
        self.assertNotIn('cmd.extend(["bash", "/opt/cage/build/run.sh"])', executor)
        self.assertNotIn("xvfb-entrypoint", executor.lower())

    def test_selkies_launcher_preserves_inherited_init(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "runtime/launcher.py").read_text(encoding="utf-8")
        self.assertIn("CAGE_LAUNCH_SCRIPT_B64", launcher)
        self.assertIn("argv.append(image)", launcher)

    def test_default_wine_image_does_not_ship_build_toolchains(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "container/runtimes/wine/Dockerfile").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("build-essential", dockerfile)
        self.assertNotIn("gcc-mingw-w64", dockerfile)
        self.assertNotIn("rustup", dockerfile)
        self.assertNotIn("cargo", dockerfile)
        self.assertNotIn("/root/.cargo", dockerfile)


if __name__ == "__main__":
    unittest.main()
