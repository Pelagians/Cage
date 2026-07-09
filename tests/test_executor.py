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
    "schemaVersion": "cage.app/v0",
    "name": "sample",
    "version": "1.0.0",
    "runtime": {"provider": "wine", "version": "9.0"},
    "modules": [
        {"type": "winetricks", "verbs": ["corefonts"]},
        {"type": "portable", "source": "file://app.zip", "target": "C:/Program Files/App"},
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
            plan = build_run_plan(bundle, graphics="headless", engine="podman", allow_non_runnable=True)

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
                build_run_plan(bundle, graphics="headless", engine="podman", allow_non_runnable=True)

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

    def test_build_run_plan_rejects_invalid_graphics_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            with self.assertRaises(RunError) as cm:
                build_run_plan(bundle, graphics="wayland", engine="docker", allow_non_runnable=True)

        self.assertIn("graphics mode 'wayland' must be one of", str(cm.exception))

    def test_build_run_plan_rejects_invalid_graphics_contract_before_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            graph_path = bundle / "metadata" / "graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["graphics"]["supportedModes"] = ["headless"]
            graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
            with self.assertRaises(RunError) as cm:
                build_run_plan(bundle, graphics="vnc", engine="docker", allow_non_runnable=True)

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
            allow_non_runnable=True,
            )

        argv = plan["container"]["argv"]
        self.assertIn("127.0.0.1:5901:5900", argv)
        self.assertIn("127.0.0.1:6081:6080", argv)
        self.assertIn("x11vnc", plan["container"]["script"])
        self.assertIn("websockify", plan["container"]["script"])

    def test_run_plan_clears_inherited_base_image_dll_overrides_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle(tmp)
            plan = build_run_plan(bundle, graphics="headless", engine="docker", allow_non_runnable=True)

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
            plan = build_run_plan(bundle, graphics="headless", engine="docker", allow_non_runnable=True)

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
            plan = build_run_plan(bundle, graphics="headless", engine="podman", allow_non_runnable=True)

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
                self.assertIn("novnc", dockerfile)

    def test_vnc_launcher_accepts_debian_novnc_assets(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "runtime/launcher.py").read_text(encoding="utf-8")

        self.assertIn("/usr/share/novnc", launcher)

    def test_default_wine_image_does_not_ship_build_toolchains(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "container/runtimes/wine/Dockerfile").read_text(encoding="utf-8")

        self.assertNotIn("build-essential", dockerfile)
        self.assertNotIn("gcc-mingw-w64", dockerfile)
        self.assertNotIn("rustup", dockerfile)
        self.assertNotIn("cargo", dockerfile)
        self.assertNotIn("/root/.cargo", dockerfile)

    def test_umu_final_image_does_not_ship_git_or_pip_install_tooling(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "container/runtimes/umu-proton-ge/Dockerfile").read_text(encoding="utf-8")
        final_stage = dockerfile.split("FROM ge-download AS final", 1)[1]

        self.assertNotIn(" git ", final_stage)
        self.assertNotIn("python3-venv", final_stage)
        self.assertNotIn("pip install", final_stage)
        self.assertIn("COPY --from=umu-build /opt/umu /opt/umu", dockerfile)

    def test_wine_runtime_images_ship_powershell_runtime_smoke(self):
        root = Path(__file__).resolve().parents[1]
        smoke = (root / "container/common/cage-powershell-runtime-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("PowerShell-7.5.5-win-x64.msi", smoke)
        self.assertIn("b2ac56b7639e2b259bb78bab077555d76f2a5eec6c516690d63de36bc1d6ca25", smoke)
        self.assertIn("PWSH-ALIVE", smoke)
        self.assertIn("cage-pwsh-smoke-ok.txt", smoke)
        self.assertIn("try_pwsh_launch direct", smoke)
        self.assertIn("try_pwsh_launch cmd", smoke)
        self.assertIn("try_pwsh_launch cmdfile", smoke)
        self.assertIn("run-smoke.cmd", smoke)
        self.assertIn('wine cmd /s /c "$SMOKE_LAUNCHER_WIN"', smoke)
        self.assertIn('call "%s" -NoLogo -NoProfile -ExecutionPolicy Bypass', smoke)
        self.assertNotIn('wine cmd /s /c "\\\"$SMOKE_LAUNCHER_WIN\\\""', smoke)
        self.assertIn("POWER SHELL RUNTIME SMOKE PASSED", smoke)
        self.assertIn("github_error", smoke)
        self.assertIn("CAGE_GITHUB_ANNOTATIONS", smoke)
        self.assertIn("CAGE_GITHUB_ANNOTATION_LEVEL", smoke)
        self.assertIn("Wine prefix initialization failed", smoke)
        self.assertIn("Wine win10 configuration failed", smoke)
        self.assertIn("PowerShell MSI checksum mismatch", smoke)
        self.assertIn("PowerShell MSI did not install pwsh.exe", smoke)
        self.assertIn("Preparing pwsh.exe Wine DLL overrides", smoke)
        self.assertIn("reg_add_pwsh_override", smoke)
        self.assertIn("PowerShell DLL override registry prep failed", smoke)
        self.assertIn("HKCU\\Software\\Wine\\AppDefaults\\pwsh.exe\\DllOverrides", smoke)
        self.assertNotIn("HKCU\\\\Software\\\\Wine\\\\AppDefaults", smoke)
        self.assertIn("rpcrt4", smoke)
        self.assertIn("PowerShell launch failed", smoke)
        self.assertIn("No PowerShell launch mode produced runtime proof", smoke)
        self.assertIn("run_pwsh_winedebug_probe", smoke)
        self.assertIn("PowerShell WINEDEBUG probe", smoke)
        self.assertIn("+loaddll,+seh", smoke)
        self.assertIn("CAGE_POWERSHELL_DEBUG_TIMEOUT", smoke)
        self.assertIn("wait_for_wine_launch_children", smoke)
        self.assertIn("CAGE_POWERSHELL_SMOKE_SETTLE_TIMEOUT", smoke)
        self.assertIn("wineserver -w", smoke)
        self.assertIn("stderr_tail_b64=", smoke)
        self.assertIn("sentinel=", smoke)
        self.assertIn("stdout_bytes=", smoke)
        self.assertIn("stderr_bytes=", smoke)
        self.assertIn("stdout_b64=", smoke)
        self.assertIn("stderr_b64=", smoke)
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

        self.assertIn("Observe deprecated PowerShell runtime smoke on wine 11.0", workflow)
        self.assertIn("matrix.provider == 'wine' && matrix.version == '11.0'", workflow)
        self.assertIn("github.sha", workflow)
        self.assertIn("cage-powershell-runtime-smoke", workflow)
        self.assertIn("--shm-size 2g", workflow)
        self.assertIn("-e CAGE_GITHUB_ANNOTATIONS=1", workflow)
        self.assertIn("-e CAGE_GITHUB_ANNOTATION_LEVEL=warning", workflow)
        self.assertIn("shell: bash", workflow)
        self.assertIn("PIPESTATUS[0]", workflow)
        self.assertIn("Deprecated PowerShell smoke failed", workflow)
        self.assertIn("Deprecated PowerShell smoke passed", workflow)
        self.assertIn("tee \"$LOG\"", workflow)
        self.assertIn("tail -80", workflow)
        self.assertIn("summary=\"${summary//$'\\n'/'%0A'}\"", workflow)
        self.assertIn("Compare PowerShell runtime smoke on candidate Wine images", workflow)
        self.assertIn("matrix.provider == 'staging'", workflow)
        self.assertIn("matrix.version == '10.0'", workflow)
        self.assertIn("CAGE_GITHUB_ANNOTATION_LEVEL=warning", workflow)
        self.assertIn("Candidate PowerShell smoke failed", workflow)
        self.assertIn("Candidate PowerShell smoke passed", workflow)


if __name__ == "__main__":
    unittest.main()
