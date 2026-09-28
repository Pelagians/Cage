"""Retired schema and enforced build-step contracts."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from core.build_step import BuildStep
from core.manifest import Manifest, ManifestError
from core.modules import ModuleError, parse_module
from builder.executor import execute_inside_container

BASE = {"schemaVersion": "cage.app/v0", "name": "contract", "version": "1",
        "runtime": {"provider": "wine", "version": "latest"}}


class CleanupContractTests(unittest.TestCase):
    def test_only_one_parser_and_no_expansion_files(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "core/manifest/manifest_old.py").exists())
        self.assertFalse((root / "core/manifest/types.py").exists())
        self.assertFalse((root / "core/profiles.py").exists())
        self.assertFalse((root / "core/modules/containerfile.py").exists())

    def test_retired_schema_and_module_options_are_rejected(self):
        for field, value in (("profiles", ["office-legacy-32bit"]),
                             ("dependencies", []), ("install", []), ("filesystem", [])):
            with self.subTest(field=field), self.assertRaisesRegex(ManifestError, field):
                Manifest.from_dict({**BASE, field: value})
        for module in ({"type": "containerfile", "instructions": ["RUN true"]},
                       {"type": "portable", "source": "app.zip", "target": "C:/app", "config": "ignored"}):
            with self.subTest(module=module), self.assertRaises(ModuleError):
                parse_module(module)

    def test_entrypoint_metadata_validation(self):
        valid = {**BASE, "entrypoints": [{"id": "writer", "name": "Writer", "executable": "C:/writer.exe"}]}
        for payload in (
            {**valid, "entrypoints": valid["entrypoints"] * 2},
            {**valid, "entrypoints": [{**valid["entrypoints"][0], "args": "bad"}]},
            {**valid, "fileAssociations": [{"entrypoint": "missing", "extensions": [".txt"]}]},
            {**valid, "fileAssociations": [{"entrypoint": "writer", "extensions": ["txt"]}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ManifestError):
                Manifest.from_dict(payload)
        Manifest.from_dict({**valid, "fileAssociations": [{"entrypoint": "writer", "extensions": [".txt"]}]})

    def test_build_step_timeout_and_cwd_are_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "marker"
            step = BuildStep(commands=["pwd > marker"], description="cwd", working_dir=tmp)
            subprocess.run(["bash", "-c", "set -e\n" + "\n".join(step.to_shell_lines())], check=True)
            self.assertEqual(marker.read_text().strip(), tmp)
            timed = BuildStep(commands=["sleep 2"], description="timeout", timeout=1)
            result = subprocess.run(["bash", "-c", "set -e\n" + "\n".join(timed.to_shell_lines())])
            self.assertEqual(result.returncode, 124)

    def test_stop_before_rejected_before_executor_side_effects(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            execute_inside_container(Manifest.from_dict(BASE), Path("/does-not-exist"),
                                     stop_before="install-apps")


if __name__ == "__main__":
    unittest.main()
