"""Fail-closed acquisition boundaries for the standalone macOS experiment."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("macos_proof", ROOT / "scripts/test-macos-runtime-poc.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class MacOSProofTests(unittest.TestCase):
    def metadata(self):
        lock = json.loads(proof.LOCK.read_text())
        release = {"id": lock["releaseId"], "tag_name": lock["tag"], "assets": []}
        for spec in (lock["asset"], lock["checksums"]):
            release["assets"].append({**spec, "id": spec.get("id", 1), "digest": "sha256:" + spec["sha256"],
                                     "browser_download_url": f"https://github.com/{lock['repository']}/releases/download/{lock['tag']}/{spec['name']}"})
        commit = {"sha": lock["sourceCommit"], "commit": {"tree": {"sha": lock["sourceTree"]}}}
        tree = {"sha": lock["sourceTree"], "tree": [{"path": p, "sha": sha, "type": "commit"} for p, sha in lock["sourcePins"].items()]}
        tag = {"type": "commit", "sha": lock["sourceCommit"]}
        return lock, release, commit, tree, tag

    def test_asset_tag_and_source_drift_fail_before_runtime_execution(self):
        baseline = self.metadata()
        proof.verify_metadata(*baseline)
        for mutate in (lambda v: v[1]["assets"][0].update(digest="sha256:" + "0" * 64),
                       lambda v: v[3]["tree"][0].update(sha="0" * 40),
                       lambda v: v[4].update(sha="0" * 40),
                       lambda v: v[3].update(truncated=True)):
            value = copy.deepcopy(baseline)
            mutate(value)
            with self.assertRaises(ValueError):
                proof.verify_metadata(*value)

    def test_cached_bytes_are_rehashed_without_replacing_changed_content(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "asset"
            path.write_bytes(b"changed")
            with patch.object(proof.urllib.request, "urlopen") as network:
                with self.assertRaisesRegex(ValueError, "checksum"):
                    proof.download("https://example.invalid", path, hashlib.sha256(b"expected").hexdigest(), 100)
                network.assert_not_called()
            self.assertEqual(path.read_bytes(), b"changed")

    def test_archive_escape_and_external_links_do_not_extract(self):
        for name, link in (("../escaped", None), ("runtime/link", "/etc/passwd")):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                archive = root / "asset.tar.xz"
                with tarfile.open(archive, "w:xz") as tar:
                    item = tarfile.TarInfo(name)
                    if link:
                        item.type = tarfile.SYMTYPE
                        item.linkname = link
                        tar.addfile(item)
                    else:
                        item.size = 1
                        tar.addfile(item, io.BytesIO(b"x"))
                with self.assertRaises((ValueError, tarfile.FilterError)):
                    proof.extract_runtime(archive, root / "out", "runtime")
                self.assertFalse((root / "escaped").exists())

    def test_application_pin_is_the_existing_asahi_x64_input(self):
        lock = json.loads(proof.LOCK.read_text())
        from core.manifest import load_manifest
        for name in (lock["applicationRecipe"], "recipes/notepadplusplus-portable-arm64.cage.yaml"):
            manifest = load_manifest(ROOT / name)
            self.assertEqual(manifest.sources[0].sha256, lock["applicationSha256"])
            self.assertIn("x64", manifest.sources[0].url)

    def test_only_bounded_appledouble_metadata_with_a_contained_counterpart_is_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "asset.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                item = tarfile.TarInfo("runtime"); item.type = tarfile.DIRTYPE; tar.addfile(item)
                item = tarfile.TarInfo("._runtime"); data = bytes.fromhex("0005160700020000") + b"metadata"
                item.size = len(data); tar.addfile(item, io.BytesIO(data))
                item = tarfile.TarInfo("runtime/file"); item.size = 7; tar.addfile(item, io.BytesIO(b"payload"))
            evidence = root / "evidence"; evidence.mkdir()
            runtime = proof.extract_runtime(archive, root / "out", "runtime", evidence)
            self.assertEqual((runtime / "file").read_bytes(), b"payload")
            self.assertFalse((root / "out/._runtime").exists())
            self.assertEqual(len(json.loads((evidence / "archive-metadata.json").read_text())["omittedAppleDouble"]), 1)
