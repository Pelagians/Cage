"""CI workflow contract tests."""

from __future__ import annotations

import json
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
    def test_cfw_proofs_bound_readiness_before_live_process_capture(self):
        for name in ("chocolatey-smoke.yml", "chocolatey-public-package-proof.yml"):
            text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn("CAGE_CHOCOLATEY_VERIFY_TIMEOUT: '60s'", text)
            self.assertIn("CAGE_CHOCOLATEY_VERIFY_SETTLE_TIMEOUT: '30s'", text)
        lifecycle = (ROOT / ".github/workflows/chocolatey-smoke.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("choco-live-process-tree.log", lifecycle)

    def test_lifecycle_runs_only_for_universal_cfw_runtime(self):
        text = (ROOT / ".github/workflows/chocolatey-smoke.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("qualified:", text)
        self.assertIn("sessionContract", text)
        self.assertIn("docker build", text)
        self.assertIn("--runtime-image", text)
        self.assertIn("--runtime-image", text)
        self.assertIn("--requalify-cfw-runtime", text)
        self.assertNotIn("needs.runtime-profile.outputs.qualified == 'true'", text)

    def test_public_package_proof_runs_only_for_universal_cfw_runtime(self):
        profile = json.loads(
            (
                ROOT / "core/chocolatey/assets/cfw-runtime-v1.0.5-wine-11.0.json"
            ).read_text(encoding="utf-8")
        )
        text = (
            ROOT / ".github/workflows/chocolatey-public-package-proof.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(profile["sessionContract"], "cage.selkies-wayland/v1")
        self.assertIn("qualified:", text)
        self.assertIn("if: needs.runtime-profile.outputs.qualified == 'true'", text)
        self.assertIn("needs.runtime-profile.outputs.image", text)
        self.assertIn("strategy:", text)
        self.assertIn("fail-fast: false", text)
        self.assertIn("package: 7zip", text)
        self.assertIn("package: notepadplusplus", text)
        self.assertIn("cage run --dry-run", text)
        self.assertNotIn("docker build", text)
        self.assertNotIn("--requalify-cfw-runtime", text)
