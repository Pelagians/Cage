"""Architectural contract tests for ordered application operations."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from artifact.bundle import create_bundle
from artifact.graph import build_execution_graph
from artifact.inspection import verify_bundle
from artifact.linux_state import linux_state_identity
from artifact.oci import create_oci_export_plan, prepare_oci_build_context
from builder.pipeline import build_plan, generate_build_script
from builder.executor import _immutable_image_ref, _verify_iso_host_mounts, _verify_root_build_capability
from core.manifest import Manifest
from core.manifest.helpers import _load_strict_yaml
from core.media import MediaStageError, extract_archive
from core.modules.registry import compile_reg
from core.sources import verify_manifest_sources
from runtime.launcher import build_run_plan


def manifest(modules, *, compatibility=None):
    return Manifest.from_dict({"schemaVersion": "cage.app/v0", "name": "ordered",
                               "version": "1", "runtime": {"provider": "wine", "version": "11.0"},
                               "modules": modules, "compatibility": compatibility or {},
                               "launch": {"entrypoint": "C:/App/app.exe"}})


class OrderedPlanTests(unittest.TestCase):
    def test_interleaved_modules_match_plan_graph_provenance_and_script(self):
        modules = [{"type": "install", "source": "vendor.msi"},
                   {"type": "files", "mappings": [{"source": "config.ini", "target": "C:/App/config.ini"}]},
                   {"type": "registry", "changes": [{"action": "set", "key": "HKCU\\Software\\Vendor", "name": "Ready", "type": "dword", "value": 1}]},
                   {"type": "install", "source": "second.exe", "args": ["/quiet"]},
                   {"type": "check", "file": {"path": "C:/App/app.exe", "exists": True}}]
        recipe = manifest(modules)
        plan = build_plan(recipe)
        ordered = [op for op in plan if "moduleIndex" in op]
        self.assertEqual([op["moduleIndex"] for op in ordered], [1, 2, 3, 4, 5])
        self.assertEqual([op["kind"] for op in ordered], ["install-msi", "copy-tree", "registry", "install-exe", "check"])
        script = generate_build_script(recipe)
        positions = [script.index("Operation " + op["id"] + ":") for op in ordered]
        self.assertEqual(positions, sorted(positions))
        graph = build_execution_graph(recipe)
        nodes = [node["id"] for node in graph["nodes"] if node["id"].startswith("phase:")]
        self.assertEqual(nodes, ["phase:" + op["id"] for op in plan])
        with tempfile.TemporaryDirectory() as temp:
            bundle = create_bundle(recipe, Path(temp), dry_run=True)
            provenance = json.loads((bundle / "metadata/provenance.json").read_text())
            self.assertEqual([op["id"] for op in provenance["operations"]], [op["id"] for op in plan])

    def test_prefix_affecting_environment_precedes_one_initialization(self):
        recipe = manifest([{"type": "install", "source": "a.exe"}], compatibility={"arch": "win32"})
        plan = build_plan(recipe)
        self.assertEqual(sum(op["phase"] == "init-prefix" for op in plan), 1)
        script = generate_build_script(recipe)
        self.assertLess(script.index("export WINEARCH="), script.index("wine wineboot --init"))

    def test_chocolatey_foundation_once_before_interleaved_actions(self):
        recipe = manifest([{"type": "chocolatey", "packages": ["7zip"]},
                           {"type": "files", "mappings": [{"source": "a", "target": "C:/App/a"}]},
                           {"type": "chocolatey", "packages": ["git"]}])
        plan = build_plan(recipe)
        self.assertEqual(sum(op["kind"] == "prefix-seed" for op in plan), 1)
        self.assertEqual(sum(op["kind"] == "prefix-adopt" for op in plan), 1)
        modules = [op for op in plan if "moduleIndex" in op]
        self.assertEqual([op["moduleIndex"] for op in modules], [1, 2, 3])
        self.assertLess(next(i for i, op in enumerate(plan) if op["kind"] == "prefix-seed"),
                        next(i for i, op in enumerate(plan) if op.get("moduleIndex") == 1))
        self.assertIn("runtimeArtifact", recipe.to_dict()["modules"][0]["install"])

    def test_install_inference_options_and_unsupported_fields(self):
        module = manifest([{"type": "install", "source": "setup.EXE", "args": ["/q", "two words"],
                            "workingDirectory": "C:/App", "timeout": 21, "expectedExitCodes": [0, 42],
                            "environment": {"FOO": "bar"}}]).modules[0]
        self.assertEqual(module.mechanism(), "exe")
        step = module.build()[0]
        self.assertIn("'two words'", step.commands[0])
        self.assertEqual((step.working_dir, step.timeout, step.environment), ("C:/App", 21, {"FOO": "bar"}))
        self.assertIn("0|42", step.commands[0])
        self.assertIn('dosdevices/c:', "\n".join(step.to_shell_lines()))
        self.assertEqual(manifest([{"type": "install", "source": "x.bin", "installer": "msi"}]).modules[0].mechanism(), "msi")
        for invalid in ({"type": "install", "source": "x.bin"}, {"type": "install", "source": "a.exe", "silentArgs": "/q"},
                        {"type": "install", "source": "a.exe", "timeout": 0},
                        {"type": "exe", "source": "a.exe"}, {"type": "msi", "source": "a.msi"},
                        {"type": "wine-patch", "source": "runtime.patch"}):
            with self.subTest(invalid=invalid), self.assertRaises(Exception): manifest([invalid])

    def test_media_resource_lifetime_and_explicit_installer(self):
        modules = [{"type": "iso", "action": "mount", "id": "disc", "source": "disc.iso", "mountPath": "mounted/disc", "drive": "D"},
                   {"type": "install", "source": "D:/setup.exe", "installer": "exe", "workingDirectory": "D:/", "args": ["/quiet"]},
                   {"type": "iso", "action": "unmount", "id": "disc"}]
        plan = build_plan(manifest(modules))
        media = [op for op in plan if op["kind"].startswith("media-")]
        self.assertEqual([op["kind"] for op in media], ["media-mount", "media-unmount"])
        self.assertIn("dosdevices/d:", "\n".join(media[0]["commands"]))
        self.assertNotIn("mount -o loop", generate_build_script(manifest(modules)))
        self.assertNotIn("autorun.exe", generate_build_script(manifest(modules)))
        with self.assertRaisesRegex(Exception, "active media drive"):
            build_plan(manifest([modules[1]]))
        with self.assertRaisesRegex(Exception, "unknown media"):
            build_plan(manifest([modules[2]]))
        pending = build_plan(manifest(modules[:2]))
        self.assertEqual(pending[-3]["kind"], "media-cleanup")
        with self.assertRaisesRegex(Exception, "unknown module field"):
            manifest([{"type": "iso", "source": "disc.iso", "autorun": True}])

    def test_iso_backend_rejects_non_mounts_and_writable_mounts(self):
        recipe = manifest([{"type": "iso", "action": "mount", "id": "disc", "source": "disc.iso",
                            "mountPath": "media", "drive": "D"}])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "media").mkdir()
            with self.assertRaisesRegex(RuntimeError, "real operator-mounted"):
                _verify_iso_host_mounts(recipe, root)
            fake_stat = type("Stat", (), {"f_flag": 0})()
            with patch("builder.executor.os.path.ismount", return_value=True), \
                 patch("builder.executor.os.statvfs", return_value=fake_stat):
                with self.assertRaisesRegex(RuntimeError, "read-only"):
                    _verify_iso_host_mounts(recipe, root)
            fake_stat.f_flag = os.ST_RDONLY
            with patch("builder.executor.os.path.ismount", return_value=True), \
                 patch("builder.executor.os.statvfs", return_value=fake_stat):
                _verify_iso_host_mounts(recipe, root)

    def test_script_file_and_inline_capture_only_declared_linux_paths(self):
        inline = {"type": "script", "run": "mkdir -p /etc/vendor", "outputs": ["/etc/vendor"], "timeout": 5}
        file = {"type": "script", "file": "scripts/setup.sh", "outputs": ["/opt/vendor"], "shell": "/bin/sh"}
        plan = build_plan(manifest([inline, file]))
        self.assertEqual([op["kind"] for op in plan if op.get("moduleType") == "script"], ["raw-shell", "raw-shell"])
        self.assertTrue(all(op["unsafe"] for op in plan if op.get("moduleType") == "script"))
        self.assertEqual([op["metadata"]["path"] for op in plan if op["kind"] == "linux-state"], ["/etc/vendor", "/opt/vendor"])
        self.assertEqual(sum(op["kind"] == "linux-seal" for op in plan), 1)
        self.assertEqual([op["executionUser"] for op in plan if op.get("moduleType") == "script"], ["root", "root"])
        self.assertEqual(next(op for op in plan if op["kind"] == "wineboot")["executionUser"], "application")
        self.assertIn("s6-setuidgid abc", generate_build_script(manifest([inline, file])))
        for bad in ({"type": "script", "run": "true"},
                    {"type": "script", "command": "true"},
                    {"type": "script", "run": "true", "file": "x", "outputs": ["/etc/vendor"]},
                    {"type": "script", "run": "true", "outputs": ["/init"]},
                    {"type": "script", "run": "true", "outputs": ["/usr/bin/x"]}):
            with self.subTest(bad=bad), self.assertRaises(Exception): manifest([bad])

    def test_root_build_requires_qualified_runtime_capability(self):
        response = type("Result", (), {"returncode": 0, "stdout": "v1\n"})()
        with patch("builder.executor.subprocess.run", return_value=response) as inspected:
            _verify_root_build_capability("docker", "qualified@sha256:abc")
        self.assertIn("root-build-operations", inspected.call_args.args[0][-2])
        response.stdout = "<no value>\n"
        with patch("builder.executor.subprocess.run", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "root-build-operations=v1"):
                _verify_root_build_capability("docker", "old-runtime")
        digest = "ghcr.io/pelagians/cage-wine@sha256:" + "a" * 64
        response.stdout = json.dumps([digest])
        with patch("builder.executor.subprocess.run", return_value=response):
            self.assertEqual(_immutable_image_ref("podman", "ghcr.io/pelagians/cage-wine:11.0"), digest)
        response.stdout = "[]"
        with patch("builder.executor.subprocess.run", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "immutable producer image digest"):
                _immutable_image_ref("podman", "mutable:latest")

    def test_registry_dll_and_checks_are_ordered_with_evidence(self):
        modules = [{"type": "registry", "changes": [
            {"action": "set", "key": "HKCU\\Software\\Vendor", "type": "string", "value": "default"},
            {"action": "deleteValue", "key": "HKCU\\Software\\Vendor", "name": "Old"},
            {"action": "deleteKey", "key": "HKLM\\Software\\Old"}]},
            {"type": "dll", "install": {"source": "vendor.dll", "target": "syswow64", "sha256": "a" * 64},
             "overrides": {"vendor": "native,builtin"},
             "evidence": {"id": "vendor-fix", "runtime": "wine-11.0"}},
            {"type": "check", "file": {"path": "C:/App/app.exe", "exists": True}}]
        plan = build_plan(manifest(modules))
        self.assertEqual([op["kind"] for op in plan if op.get("moduleIndex")],
                         ["registry", "dll-deploy", "dll-overrides", "check"])
        compiled = compile_reg(modules[0]["changes"])
        self.assertIn('@="default"', compiled)
        self.assertIn('"Old"=-', compiled)
        self.assertIn('[-HKEY_LOCAL_MACHINE\\Software\\Old]', compiled)
        variants = compile_reg([
            {"action": "set", "key": "HKCU\\Software\\Vendor", "type": "expandString", "value": "%APPDATA%"},
            {"action": "set", "key": "HKCU\\Software\\Vendor", "name": "Big", "type": "qword", "value": 2**40},
            {"action": "set", "key": "HKCU\\Software\\Vendor", "name": "Raw", "type": "binary", "value": "00ff"},
            {"action": "deleteValue", "key": "HKCU\\Software\\Vendor"},
        ])
        self.assertIn("@=hex(2):", variants)
        self.assertIn('"Big"=hex(b):', variants)
        self.assertIn('"Raw"=hex:00,ff', variants)
        self.assertIn("@=-", variants)
        self.assertEqual(plan[4]["metadata"]["evidence"]["runtime"], "wine-11.0")
        self.assertIn("native,builtin", "\n".join(plan[4]["commands"]))
        self.assertIn("syswow64", "\n".join(plan[3]["commands"]))
        for unsupported in ({"type": "registry", "file": "a.reg", "changes": modules[0]["changes"]},
                            {"type": "registry", "changes": modules[0]["changes"], "view": "32"},
                            {"type": "dll", "install": {"source": "x.dll", "target": "system32"}}):
            with self.subTest(unsupported=unsupported), self.assertRaises(Exception): manifest([unsupported])
        with self.assertRaisesRegex(Exception, "syswow64 requires"):
            build_plan(manifest([modules[1]], compatibility={"arch": "win32"}))

    def test_iso_extraction_selects_backend_and_fails_without_it(self):
        with self.assertRaisesRegex(Exception, "backend must explicitly select"):
            manifest([{"type": "extract", "source": "disc.iso", "target": "/work/disc"}])
        operation = next(op for op in build_plan(manifest([{"type": "extract", "source": "disc.iso",
                                                            "target": "/work/disc", "backend": "bsdtar"}]))
                         if op.get("moduleType") == "extract")
        self.assertEqual(operation["metadata"]["backend"], "bsdtar")
        self.assertIn("--backend bsdtar", operation["commands"][0])


class ArtifactAndSourceTests(unittest.TestCase):
    def test_inline_yaml_script_and_numeric_registry_values(self):
        parsed = _load_strict_yaml('modules:\n  - type: script\n    run: |\n      # preserve this comment\n      echo value > /etc/vendor/file\n    outputs:\n      - /etc/vendor\n  - type: registry\n    changes:\n      - action: set\n        key: HKCU\\Software\\Vendor\n        type: dword\n        value: 4\n')
        self.assertIn("# preserve this comment", parsed["modules"][0]["run"])
        self.assertTrue(parsed["modules"][0]["run"].endswith("\n"))
        self.assertEqual(parsed["modules"][1]["changes"][0]["value"], 4)

    def test_new_inputs_are_verified_and_hashes_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, data in (("app.msi", b"msi"), ("config.reg", b"reg"), ("setup.sh", b"script"),
                               ("disc.iso", b"iso"), ("vendor.dll", b"dll"), ("archive.zip", b"zip")):
                (root / name).write_bytes(data)
            digest = lambda name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            recipe = manifest([{"type": "install", "source": "app.msi", "sha256": digest("app.msi")},
                               {"type": "registry", "file": "config.reg", "sha256": digest("config.reg")},
                               {"type": "script", "file": "setup.sh", "sha256": digest("setup.sh"),
                                "outputs": ["/etc/vendor"]},
                               {"type": "extract", "source": "archive.zip", "target": "/work/archive"},
                               {"type": "dll", "install": {"source": "vendor.dll", "target": "system32", "sha256": digest("vendor.dll")}}])
            result = verify_manifest_sources(recipe, workspace=root)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["summary"]["checked"], 5)
            (root / "app.msi").write_bytes(b"tampered")
            self.assertFalse(verify_manifest_sources(recipe, workspace=root)["valid"])
            (root / "media").mkdir()
            iso_recipe = manifest([{"type": "iso", "action": "mount", "id": "disc", "source": "disc.iso",
                                    "sha256": digest("disc.iso"), "mountPath": "media", "drive": "D"}])
            self.assertTrue(verify_manifest_sources(iso_recipe, workspace=root)["valid"])
            (root / "disc.iso").write_bytes(b"altered")
            self.assertFalse(verify_manifest_sources(iso_recipe, workspace=root)["valid"])
            unsafe = manifest([{"type": "install", "source": "../outside/setup.exe"}])
            self.assertFalse(verify_manifest_sources(unsafe, workspace=root)["valid"])

    def test_linux_snapshot_is_shared_by_run_and_oci_export(self):
        recipe = manifest([{"type": "script", "run": "mkdir -p /etc/vendor", "outputs": ["/etc/vendor"]}])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = create_bundle(recipe, root, dry_run=True)
            output = bundle / "linux-root/etc/vendor"
            output.mkdir(parents=True)
            (output / "config").write_text("preserved")
            archive_path = bundle / "linux-state.tar"
            def pack():
                with tarfile.open(archive_path, "w") as archive:
                    archive.add(output, arcname="etc/vendor")
            pack()
            base = build_execution_graph(recipe)["runnerRuntime"]["image"]
            identity = linux_state_identity(bundle, base)
            self.assertIsNotNone(identity)
            with patch("runtime.launcher.verify_bundle", return_value={"valid": True, "runnable": True}), \
                 patch("artifact.oci.verify_bundle", return_value={"valid": True, "runnable": True}):
                run = build_run_plan(bundle, engine="docker")
                export = create_oci_export_plan(bundle, tag="test:latest")
            self.assertIn(identity, run["container"]["image"])
            self.assertEqual(export["derivedRuntimeImage"], identity)
            self.assertIn("ADD linux-state.tar /", export["containerfile"]["content"])
            context = prepare_oci_build_context(bundle, export, root / "context")
            with tarfile.open(context / "linux-state.tar") as archive:
                self.assertEqual(archive.extractfile("etc/vendor/config").read(), b"preserved")
            (bundle / "metadata/linux-state.json").write_text(json.dumps({
                "schemaVersion": "cage.linux-state/v0", "baseImage": base,
                "derivedRuntimeImage": identity, "outputs": ["/etc/vendor"]}))
            status = json.loads((bundle / "metadata/status.json").read_text())
            status["state"] = "build-passed"
            (bundle / "metadata/status.json").write_text(json.dumps(status))
            check = lambda: next(item for item in verify_bundle(bundle)["checks"] if item["id"] == "linux-artifact-state")
            self.assertTrue(check()["ok"])
            (output / "config").write_text("changed")
            pack()
            self.assertNotEqual(linux_state_identity(bundle, base), identity)
            self.assertFalse(check()["ok"])
            with tarfile.open(archive_path, "w") as archive:
                info = tarfile.TarInfo("usr/local/bin/unqualified")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(ValueError, "unsafe Linux layer member"):
                linux_state_identity(bundle, base)

    def test_safe_extraction_zip_tar_and_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            z = root / "good.zip"
            with zipfile.ZipFile(z, "w") as archive: archive.writestr("setup.exe", "payload")
            self.assertEqual(extract_archive(z, root / "unzipped"), "zip")
            self.assertEqual((root / "unzipped/setup.exe").read_text(), "payload")
            t = root / "good.tar.gz"
            with tarfile.open(t, "w:gz") as archive:
                info = tarfile.TarInfo("setup.exe"); info.size = 3
                archive.addfile(info, io.BytesIO(b"exe"))
            self.assertEqual(extract_archive(t, root / "untarred"), "tar")
            self.assertEqual((root / "untarred/setup.exe").read_bytes(), b"exe")
            with self.assertRaises(MediaStageError): extract_archive(z, root / "unzipped")
            bad = root / "bad.zip"
            with zipfile.ZipFile(bad, "w") as archive: archive.writestr("../escape", "bad")
            with self.assertRaises(MediaStageError): extract_archive(bad, root / "blocked")
            self.assertFalse((root / "escape").exists())
            with self.assertRaises(MediaStageError): extract_archive(z, root / "quota", max_bytes=1)


if __name__ == "__main__": unittest.main()
