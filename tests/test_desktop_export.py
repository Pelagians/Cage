"""Desktop target integrity, persistence, and existing-workflow boundaries."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from artifact.bundle import create_bundle
from artifact.inspection import verify_bundle
from artifact.desktop import create_desktop_export_plan, desktop_target, seal_desktop_bundle, validate_desktop_recipe
from artifact.flatpak import create_flatpak_export_plan, prepare_flatpak_context
from artifact.oci import create_oci_export_plan, OCIExportError
from artifact.kube import create_kube_export_plan, KubeExportError
from builder.flatpak import snapshot_sources
from core.manifest import Manifest, ManifestError, load_manifest
from core.media import stage_media
from runtime.desktop_launch import DesktopError, digest_json, initialize_state, inventory_tree, verify_inventory, windows_path, _run_application
from runtime.launcher import build_run_plan, RunError
from tests.bundle_fixtures import materialize_runnable_prefix

ROOT = Path(__file__).resolve().parents[1]


def app():
    value = load_manifest(ROOT / "recipes/notepadplusplus-portable.cage.yaml").to_dict()
    value["name"] = "desktop-fixture"
    value.pop("sources")
    value.pop("modules")
    return value


def bundle_at(directory, machine=b"\x64\x86"):
    manifest = Manifest.from_dict(app())
    bundle = create_bundle(manifest, Path(directory), dry_run=True)
    materialize_runnable_prefix(bundle, entrypoint=manifest.launch.entrypoint)
    prefix = bundle / "prefix"
    (prefix / "dosdevices").mkdir()
    (prefix / "dosdevices/c:").symlink_to("../drive_c")
    executable = windows_path(prefix, manifest.launch.entrypoint)
    pe = bytearray(128)
    pe[:2], pe[60:64], pe[64:70] = b"MZ", (64).to_bytes(4, "little"), b"PE\0\0" + machine
    executable.write_bytes(pe)
    seal_desktop_bundle(bundle, desktop_target(), {"wineVersion": "wine-11.0"})
    (bundle / "metadata/execution-target.json").write_text(json.dumps(desktop_target()))
    return bundle


def initialize_worker(values):
    seed, inventory, state, identity = values
    return str(initialize_state(seed, inventory, state, identity))


class DesktopContractTests(unittest.TestCase):
    def test_cli_desktop_dry_run_does_not_materialize_a_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "absent"
            result = subprocess.run([sys.executable, "-m", "cage", "build",
                "recipes/notepadplusplus-portable.cage.yaml", "--target", "flatpak", "--dry-run",
                "--output", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["target"]["architecture"], "x86_64")
            self.assertFalse(output.exists())

    def test_metadata_roundtrip_and_strict_validation(self):
        value = app()
        self.assertEqual(Manifest.from_dict(value).to_dict(), value)
        for key, invalid in (("id", "org.example/escape"), ("documentsDirectory", "../Secrets"), ("name", "bad\nExec=evil")):
            candidate = copy.deepcopy(value)
            candidate["desktop"][key] = invalid
            with self.assertRaises(ManifestError):
                Manifest.from_dict(candidate)

    def test_target_rejects_cfw_and_unqualified_runtime_features(self):
        value = app()
        for changed in ({"runtime": {**value["runtime"], "version": "latest"}},
                        {"runtime": {**value["runtime"], "network": "bridge"}},
                        {"modules": [{"type": "script", "run": "true", "outputs": ["/opt/example"]}]},
                        {"launch": {**value["launch"], "env": {"WINEPREFIX": "/tmp/other"}}}):
            with self.assertRaises(DesktopError):
                validate_desktop_recipe(Manifest.from_dict({**value, **changed}))
        cfw = load_manifest(ROOT / "recipes/7zip.cage.yaml")
        with self.assertRaises(DesktopError):
            validate_desktop_recipe(cfw)

    def test_tampered_same_length_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            plan = create_desktop_export_plan(bundle)
            executable = windows_path(bundle / "prefix", plan["launch"]["entrypoint"])
            data = bytearray(executable.read_bytes()); data[-1] ^= 1
            executable.write_bytes(data)
            self.assertFalse(verify_bundle(bundle)["valid"])
            with self.assertRaises(DesktopError):
                create_desktop_export_plan(bundle)

    def test_native_wine_accepts_wow64_and_rejects_other_pe_architectures(self):
        for machine in (b"\x64\x86", b"\x4c\x01"):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as td:
                self.assertEqual(create_desktop_export_plan(bundle_at(td, machine))["target"]["architecture"], "x86_64")
        for machine in (b"\x64\xaa", b"\xc4\x01", b"\0\0"):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as td:
                with self.assertRaisesRegex(DesktopError, "architecture is unsupported"):
                    create_desktop_export_plan(bundle_at(td, machine))

    def test_old_bundle_cannot_be_silently_rebound(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = Manifest.from_dict(app())
            bundle = create_bundle(manifest, Path(td), dry_run=True)
            materialize_runnable_prefix(bundle, entrypoint=manifest.launch.entrypoint)
            self.assertTrue(verify_bundle(bundle)["valid"])
            with self.assertRaisesRegex(DesktopError, "no qualified desktop build"):
                create_desktop_export_plan(bundle)

    def test_container_and_oci_reject_desktop_bundles(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            with self.assertRaises(RunError):
                build_run_plan(bundle)
            with self.assertRaises(OCIExportError):
                create_oci_export_plan(bundle, tag="test:desktop")
            with self.assertRaises(KubeExportError):
                create_kube_export_plan(bundle, image="example.invalid/app@sha256:" + "a" * 64)

    def test_runtime_and_recipe_seals_are_checked(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            receipt = bundle / "metadata/desktop-build.json"
            payload = json.loads(receipt.read_text())
            payload["target"]["baseCommit"] = "0" * 64
            receipt.write_text(json.dumps(payload))
            with self.assertRaises(DesktopError):
                create_desktop_export_plan(bundle)

    def test_flatpak_layout_uses_one_helper_and_narrow_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = bundle_at(td)
            plan = create_flatpak_export_plan(bundle)
            def initialize(path, *args):
                (path / "files/bin").mkdir(parents=True)
            with patch("artifact.flatpak.initialize_flatpak", side_effect=initialize), \
                    patch('artifact.flatpak.run_flatpak', return_value=str(Path(td) / 'platform')), \
                    patch('artifact.flatpak.stage_desktop_fonts'):
                build = prepare_flatpak_context(bundle, plan, Path(td) / "context", store=Path(td) / "store")
            self.assertIn("--unshare=network", plan["permissions"])
            self.assertNotIn("--filesystem=home", plan["permissions"])
            self.assertTrue((build / "files/libexec/cage-desktop-launch.py").is_file())
            self.assertNotIn("cage.cli", (build / "files/libexec/cage-desktop-launch.py").read_text())
            self.assertTrue((build / "files/share/applications" / (plan["desktop"]["id"] + ".desktop")).is_file())
            metadata = build.parent / 'payload-metadata'
            self.assertEqual(json.loads((metadata / 'seed-inventory.json').read_text()),
                             json.loads((bundle / 'metadata/desktop-build.json').read_text())['inventory'])
            self.assertEqual(json.loads((metadata / 'manifest.cage.json').read_text()),
                             json.loads((bundle / 'manifest.cage.json').read_text()))
            self.assertTrue((metadata / 'component-sources.json').is_file())


class DesktopStateTests(unittest.TestCase):
    def test_second_launch_cannot_stop_an_active_application(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def execute(command, **kwargs):
            calls.append(command)
            if command[0] == "fake-wine":
                started.set()
                self.assertTrue(release.wait(5))
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as td, patch("runtime.desktop_launch.subprocess.run", side_effect=execute):
            root = Path(td)
            with ThreadPoolExecutor(1) as pool:
                first = pool.submit(_run_application, ["fake-wine", "App.exe"], "server", {}, root, root)
                self.assertTrue(started.wait(5))
                try:
                    with self.assertRaisesRegex(DesktopError, "already running"):
                        _run_application(["fake-wine", "App.exe"], "server", {}, root, root)
                    self.assertEqual(len(calls), 1, "a rejected launch must not terminate the active prefix")
                finally:
                    release.set()
                self.assertEqual(first.result(), 0)
            self.assertIn(["server", "-k"], calls)

    def seed(self, directory):
        root = Path(directory) / "seed"
        (root / "drive_c").mkdir(parents=True)
        (root / "drive_c/document").write_text("seed")
        return root, inventory_tree(root)

    def test_state_retains_app_changes_and_refuses_new_generation(self):
        with tempfile.TemporaryDirectory() as td:
            seed, inventory = self.seed(td)
            state = Path(td) / "state"
            identity = {"seed": digest_json(inventory), "runtime": "pinned"}
            prefix = initialize_state(seed, inventory, state, identity)
            (prefix / "drive_c/document").write_text("saved user settings")
            self.assertEqual(initialize_state(seed, inventory, state, identity), prefix)
            self.assertEqual((prefix / "drive_c/document").read_text(), "saved user settings")
            with self.assertRaisesRegex(DesktopError, "different seed/runtime"):
                initialize_state(seed, inventory, state, {"seed": "new"})
            verify_inventory(seed, inventory)

    def test_concurrent_first_use_and_interrupted_receipt_recover(self):
        with tempfile.TemporaryDirectory() as td:
            seed, inventory = self.seed(td)
            state = Path(td) / "state"
            values = (seed, inventory, state, {"seed": digest_json(inventory)})
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(initialize_worker, [values, values]))
            self.assertEqual(results[0], results[1])
            (state / "state.json").unlink()
            self.assertEqual(initialize_state(*values), Path(results[0]))

    def test_partial_copy_recovers_and_tampered_seed_fails(self):
        with tempfile.TemporaryDirectory() as td:
            seed, inventory = self.seed(td)
            state = Path(td) / "state"
            (state / "prefix.partial").mkdir(parents=True)
            (state / "prefix.partial/truncated").touch()
            prefix = initialize_state(seed, inventory, state, {"seed": "one"})
            self.assertFalse((prefix / "truncated").exists())
            (seed / "drive_c/document").write_text("evil")
            with self.assertRaisesRegex(DesktopError, "inventory mismatch"):
                initialize_state(seed, inventory, Path(td) / "another", {"seed": "one"})

    def test_escaping_links_special_files_and_paths_fail(self):
        with tempfile.TemporaryDirectory() as td:
            seed, _ = self.seed(td)
            (seed / "escape").symlink_to("../../outside")
            with self.assertRaises(DesktopError):
                inventory_tree(seed)
            (seed / "escape").unlink()
            os.mkfifo(seed / "fifo")
            with self.assertRaisesRegex(DesktopError, "special payload"):
                inventory_tree(seed)
            for path in ("C:/../outside", "Z:/file", "C:/folder/../../secret"):
                with self.assertRaises(DesktopError):
                    windows_path(seed, path)

    def test_unpinned_directory_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = load_manifest(ROOT / "recipes/notepadplusplus-portable.cage.yaml")
            workspace = Path(td) / "workspace"
            (workspace / manifest.modules[0].mappings[0]["source"]).mkdir(parents=True)
            with self.assertRaisesRegex(DesktopError, "media staging"):
                snapshot_sources(manifest, workspace, Path(td) / "inputs")

    def test_staged_directory_is_bound_to_archive_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            archive = workspace / "sources/pinned.zip"
            archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("config.txt", "good")
            media = stage_media(archive, name="input", workspace=workspace)
            value = app()
            value["sources"] = [{"id": "input", "type": "archive", "policy": "synthetic-fixture",
                                  "path": "sources/pinned.zip", "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]
            value["modules"] = [{"type": "files", "mappings": [{"source": "sources/input/media",
                                  "target": "C:/Program Files/App", "mode": "merge"}]}]
            manifest = Manifest.from_dict(value)
            snapshot_sources(manifest, workspace, Path(td) / "good")
            (Path(media["stagedPath"]) / "config.txt").write_text("evil")
            with self.assertRaisesRegex(DesktopError, "inventory mismatch"):
                snapshot_sources(manifest, workspace, Path(td) / "tampered")


if __name__ == "__main__":
    unittest.main()
