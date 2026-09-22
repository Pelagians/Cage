"""Tests for Cage installability and console entrypoints."""
from __future__ import annotations

import shutil
import tempfile
import zipfile
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallPackagingTests(unittest.TestCase):

    def test_pyproject_defines_cage_console_script(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["name"], "cage")
        self.assertEqual(data["project"]["scripts"]["cage"], "cage.cli:main")
        includes = set(data["tool"]["setuptools"]["packages"]["find"]["include"])
        for package in ["cage*", "core*", "runtime*", "artifact*", "builder*", "container*"]:
            self.assertIn(package, includes)
        self.assertIn("catalog.json", data["tool"]["setuptools"]["package-data"]["runtime"])
        self.assertNotIn("License :: OSI Approved :: MIT License", data["project"].get("classifiers", []))

    def test_wheel_contains_complete_selkies_overlay(self):
        # Build outside the working tree so a stale build/ or egg-info manifest
        # cannot hide missing package-data entries.
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(
                ".git", ".venv", "__pycache__", "build", "dist", "*.egg-info",
            ))
            result = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                 "--no-build-isolation", "--wheel-dir", str(Path(temporary) / "wheels")],
                cwd=source, text=True, capture_output=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            wheel = next((Path(temporary) / "wheels").glob("cage-*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                for path in (ROOT / "container/selkies/root").rglob("*"):
                    if path.is_file():
                        name = path.relative_to(ROOT).as_posix()
                        self.assertIn(name, archive.namelist())
                        self.assertEqual(archive.read(name), path.read_bytes())

    def test_package_cli_module_is_importable(self):
        from cage.cli import build_parser, main

        parser = build_parser()
        self.assertEqual(parser.prog, "cage")
        self.assertTrue(callable(main))

    def test_python_module_entrypoint_prints_help(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cage", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: cage", proc.stdout)
        self.assertIn("bundle", proc.stdout)

    def test_dev_script_shim_still_prints_help(self):
        proc = subprocess.run(
            [sys.executable, "cmd/cage.py", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: cage", proc.stdout)


if __name__ == "__main__":
    unittest.main()
