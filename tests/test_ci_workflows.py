"""CI workflow contract tests."""
from __future__ import annotations

from pathlib import Path
import unittest


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
