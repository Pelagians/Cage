"""ARM CPU translation identity and additive container/desktop boundaries."""
import io
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from artifact.bundle import create_bundle
from artifact.graph import build_execution_graph
from artifact.inspection import verify_bundle
from artifact.desktop import desktop_target, validate_desktop_recipe
from builder.executor import _immutable_image_ref
from core.manifest import load_manifest, ManifestError
from runtime.arm64ec import extract_cpio, runtime_target, verify_container_runtime, install_termination_guard
from runtime.desktop_launch import DesktopError, digest_json
from runtime.providers import resolve_runtime, resolve_manifest_runtime
from tests.bundle_fixtures import materialize_runnable_prefix

ROOT = Path(__file__).resolve().parents[1]


def cpio(entries):
    result = bytearray()
    for name, mode, data, inode, links in [*entries, ("TRAILER!!!", 0, b"", 0, 1)]:
        name = name.encode() + b"\0"
        values = (inode, mode, 0, 0, links, 0, len(data), 0, 0, 0, 0, len(name), 0)
        header = b"070701" + b"".join(f"{v:08x}".encode() for v in values)
        result.extend(header + name + b"\0" * (-(110 + len(name)) % 4))
        result.extend(data + b"\0" * (-len(data) % 4))
    return io.BytesIO(result)


class ARMRuntimeTests(unittest.TestCase):
    def test_guard_installs_exact_bundled_dll_without_mutating_rpm_hardlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dll = root / 'lib64/wine-wow64/wine/aarch64-windows/libarm64ecfex.dll'
            dll.parent.mkdir(parents=True)
            dll.write_bytes(b'pinned RPM fixture'); dll.chmod(0o755)
            retained = root / 'retained-rpm.dll'
            retained.hardlink_to(dll)
            target = runtime_target()
            target['translation']['terminationGuard']['rpmDllSha256'] = hashlib.sha256(dll.read_bytes()).hexdigest()
            with patch('runtime.arm64ec.runtime_target', return_value=target):
                install_termination_guard(root)
            source = json.loads((ROOT / 'runtime/vendor/fex-2610-cage1/source.json').read_text())
            self.assertEqual(hashlib.sha256(dll.read_bytes()).hexdigest(), source['dll']['sha256'])
            self.assertEqual(dll.stat().st_size, source['dll']['size'])
            self.assertEqual(stat.S_IMODE(dll.stat().st_mode), 0o755)
            self.assertEqual(retained.read_bytes(), b'pinned RPM fixture')
            self.assertFalse(dll.with_suffix('.dll.cage-new').exists())

    def test_guard_refuses_foreign_dll_or_source_identity_and_retains_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dll = root / 'lib64/wine-wow64/wine/aarch64-windows/libarm64ecfex.dll'
            dll.parent.mkdir(parents=True); dll.write_bytes(b'foreign')
            with self.assertRaisesRegex(DesktopError, 'exact pinned RPM'):
                install_termination_guard(root)
            target = runtime_target(); target['translation']['terminationGuard']['sourceSha256'] = '0' * 64
            with patch('runtime.arm64ec.runtime_target', return_value=target), self.assertRaisesRegex(DesktopError, 'source/build identity'):
                install_termination_guard(root)
            self.assertEqual(dll.read_bytes(), b'foreign')

    def test_catalog_runtime_is_available_through_container_build_cli(self):
        from cage.cli import main
        from container.manager import ContainerBuildResult
        result = ContainerBuildResult("wine-arm64ec", "11.20", "local:test", "Dockerfile", True)
        with patch("cage.cli.build_container", return_value=result) as build, patch("sys.stdout", io.StringIO()):
            self.assertEqual(main(["container", "build", "wine-arm64ec", "11.20", "--engine", "podman"]), 0)
            self.assertEqual(build.call_args.args[:2], ("wine-arm64ec", "11.20"))

    def recipe(self):
        return load_manifest(ROOT / "recipes/notepadplusplus-portable-arm64.cage.yaml")

    def test_recipe_resolves_same_native_lock_for_both_adapters(self):
        manifest = self.recipe()
        binding = resolve_runtime(manifest.runtime)
        self.assertEqual(binding.architecture, "aarch64")
        self.assertEqual(binding.execution_target, desktop_target("wine-arm64ec"))
        self.assertEqual(validate_desktop_recipe(manifest), runtime_target())
        self.assertEqual(binding.execution_target["windowsArchitecture"], "x86_64")
        self.assertEqual(binding.session_contract, "cage.native-wine/v1")
        graph = build_execution_graph(manifest)
        self.assertEqual(graph["graphics"]["supportedModes"], ["headless", "desktop"])
        self.assertNotIn("selkies", graph["graphics"]["supportedModes"])

    def test_native_bundle_retains_existing_verification_gates(self):
        manifest = self.recipe()
        with tempfile.TemporaryDirectory() as td:
            bundle = create_bundle(manifest, Path(td), dry_run=True)
            materialize_runnable_prefix(bundle, entrypoint=manifest.launch.entrypoint)
            (bundle / "prefix/dosdevices").mkdir()
            (bundle / "prefix/dosdevices/c:").symlink_to("../drive_c")
            from runtime.arm64ec import seal_native_bundle
            seal_native_bundle(bundle, manifest, build_execution_graph(manifest)["runnerRuntime"]["image"])
            self.assertTrue(verify_bundle(bundle)["valid"])
            from runtime.launcher import build_run_plan
            document = Path(td) / "document.txt"
            document.write_text("document")
            state = Path(td) / "new-state"
            run = build_run_plan(bundle, engine="podman", files=[document], state_dir=state,
                                 writable_files=True, require_runner=True)
            self.assertFalse(state.exists(), "planning must not initialize persistent state")
            self.assertNotIn(":ro", run["fileArguments"][0]["mount"])
            info = build_run_plan(bundle, engine="podman", state_dir=state, state_action="state-info")
            self.assertTrue(info["container"]["script"].endswith("native-launch.json --cage-state-info\n"))
            import os, sys
            result = subprocess.run([sys.executable, str(bundle / "metadata/cage-desktop-launch.py"),
                                     str(bundle / "metadata/native-launch.json"), "--cage-state-info"],
                                    env={**os.environ, "XDG_DATA_HOME": str(Path(td) / "info-state")},
                                    capture_output=True, text=True, check=True)
            self.assertIsNone(json.loads(result.stdout)["state"])

            readonly = build_run_plan(bundle, engine="podman", files=[document])
            self.assertIn(":ro", readonly["fileArguments"][0]["mount"])
            graph_path = bundle / "metadata/graph.json"
            graph = json.loads(graph_path.read_text())
            graph["runnerRuntime"]["executionTarget"]["translation"]["version"] = "other"
            graph_path.write_text(json.dumps(graph))
            self.assertFalse(verify_bundle(bundle)["valid"])

    def test_cfw_cannot_be_rebound_to_arm(self):
        from dataclasses import replace
        manifest = load_manifest(ROOT / "recipes/7zip.cage.yaml")
        manifest = replace(manifest, runtime=replace(manifest.runtime, provider="wine-arm64ec", version="11.20"))
        with self.assertRaisesRegex(ManifestError, "CFW prepared prefixes"):
            resolve_manifest_runtime(manifest)

    def test_oci_carrier_must_match_architecture_and_locked_payload(self):
        target = runtime_target()
        labels = {"org.pelagian.cage.session-contract": "cage.native-wine/v1",
                  "io.cage.runtime.target-sha256": digest_json(target)}
        def inspect(arch="arm64", override=None):
            return subprocess.CompletedProcess([], 0, json.dumps([{
                "Architecture": arch, "Config": {"Labels": override or labels}}]), "")
        with patch("runtime.arm64ec.subprocess.run", return_value=inspect()):
            verify_container_runtime("podman", "test")
        for result in (inspect("amd64"), inspect(override={"io.cage.runtime.target-sha256": "bad"})):
            with patch("runtime.arm64ec.subprocess.run", return_value=result), self.assertRaises(DesktopError):
                verify_container_runtime("podman", "test")

    def test_podman_local_repository_and_bare_image_ids_are_frozen(self):
        digest = "a" * 64
        with patch("builder.executor.subprocess.run", return_value=subprocess.CompletedProcess([], 0,
                   json.dumps(["localhost/cage/example@sha256:" + digest]), "")):
            self.assertEqual(_immutable_image_ref("podman", "cage/example:test"), "localhost/cage/example@sha256:" + digest)
        with patch("builder.executor.subprocess.run", side_effect=[
                subprocess.CompletedProcess([], 0, "[]", ""), subprocess.CompletedProcess([], 0, digest, "")]):
            self.assertEqual(_immutable_image_ref("podman", "cage/example:test"), "sha256:" + digest)

    def test_cpio_rejects_traversal_links_and_setid_payload(self):
        entries = [
            [("../escape", stat.S_IFREG | 0o644, b"x", 1, 1)],
            [("usr/bin/escape", stat.S_IFLNK | 0o777, b"../../outside", 1, 1)],
            [("usr/bin/root", stat.S_IFREG | 0o4755, b"x", 1, 1)],
            [("usr/bin/pipe", stat.S_IFIFO | 0o644, b"", 1, 1)],
        ]
        for entry in entries:
            with tempfile.TemporaryDirectory() as td, self.assertRaises(DesktopError):
                extract_cpio(cpio(entry), td)

    def test_cpio_preserves_rpm_hardlinks_and_discards_desktop_registration(self):
        entries = [("usr/bin/a", stat.S_IFREG | 0o755, b"", 1, 2),
                   ("usr/bin/b", stat.S_IFREG | 0o755, b"native", 1, 2),
                   ("usr/share/applications/wine.desktop", stat.S_IFREG | 0o644, b"ignored", 2, 1)]
        with tempfile.TemporaryDirectory() as td:
            extract_cpio(cpio(entries), td)
            root = Path(td)
            self.assertEqual((root / "bin/a").read_bytes(), b"native")
            self.assertEqual((root / "bin/a").stat().st_ino, (root / "bin/b").stat().st_ino)
            self.assertFalse((root / "share/applications/wine.desktop").exists())


if __name__ == "__main__":
    unittest.main()
