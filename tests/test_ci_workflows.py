"""CI workflow contract tests."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowTests(unittest.TestCase):
    def test_python_tests_workflow_runs_full_suite_for_core_changes(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/tests.yml").read_text(encoding="utf-8")

        self.assertIn("name: Tests", workflow)
        self.assertIn("core/**", workflow)
        self.assertIn("tests/**", workflow)
        self.assertIn("pyproject.toml", workflow)
        self.assertIn("python-version: '3.13'", workflow)
        self.assertIn("python -m pip install -e '.[dev]'", workflow)
        self.assertIn("python -m pytest tests/ -q", workflow)


if __name__ == "__main__":
    unittest.main()


class UniversalCfwWorkflowTests(unittest.TestCase):
    def test_lifecycle_runs_only_for_universal_cfw_runtime(self):
        text = (ROOT / ".github/workflows/chocolatey-smoke.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("qualified:", text)
        self.assertIn("sessionContract", text)
        self.assertIn("docker build", text)
        self.assertIn("--requalify-cfw-runtime", text)
        self.assertNotIn("needs.runtime-profile.outputs.qualified == 'true'", text)

    def test_public_package_proof_runs_only_for_universal_cfw_runtime(self):
        text = (
            ROOT / ".github/workflows/chocolatey-public-package-proof.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("qualified:", text)
        self.assertIn("docker build", text)
        self.assertIn("--requalify-cfw-runtime", text)
        self.assertNotIn("needs.runtime-profile.outputs.qualified == 'true'", text)
