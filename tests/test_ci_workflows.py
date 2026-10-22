"""CI workflow contract tests."""

from __future__ import annotations

import copy
import json
from unittest.mock import patch

import yaml
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
    def test_invalid_runtime_pin_fails_both_workflow_preflights(self):
        from core.modules.chocolatey import DEFAULT_CFW_RUNTIME_ARTIFACT
        for name in ("chocolatey-smoke.yml", "chocolatey-public-package-proof.yml"):
            workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            job = workflow["jobs"].get("runtime-profile", workflow["jobs"].get("lifecycle"))
            step = next(step for step in job["steps"] if "validate_profile(" in step.get("run", ""))
            code = step["run"].split("<<'PY'", 1)[1].split("\n", 1)[1].rsplit("\nPY", 1)[0]
            invalid = copy.deepcopy(DEFAULT_CFW_RUNTIME_ARTIFACT)
            invalid.pop("sessionContract")
            for profile in (None, invalid, {**DEFAULT_CFW_RUNTIME_ARTIFACT, "manifestSha256": "short"}):
                with self.subTest(workflow=name, profile=profile):
                    with patch("core.modules.chocolatey.DEFAULT_CFW_RUNTIME_ARTIFACT", profile):
                        with self.assertRaises(ValueError):
                            exec(code, {})

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
        self.assertIn("validate_profile(DEFAULT_CFW_RUNTIME_ARTIFACT)", text)
        self.assertIn("sessionContract", text)
        self.assertIn("docker build", text)
        self.assertIn("--runtime-image", text)
        self.assertIn("--runtime-image", text)
        self.assertIn("--requalify-cfw-runtime", text)
        self.assertNotIn("needs.runtime-profile.outputs.qualified == 'true'", text)

    def test_public_package_proof_runs_only_for_universal_cfw_runtime(self):
        profile = json.loads(
            (
                ROOT / "core/chocolatey/assets/cfw-runtime-v1.0.7-wine-11.0.json"
            ).read_text(encoding="utf-8")
        )
        text = (
            ROOT / ".github/workflows/chocolatey-public-package-proof.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(profile["sessionContract"], "cage.selkies-wayland/v1")
        self.assertIn("validate_profile(DEFAULT_CFW_RUNTIME_ARTIFACT)", text)
        self.assertNotIn("outputs.qualified", text)
        self.assertNotIn("  blocked:", text)
        self.assertIn("needs.runtime-profile.outputs.image", text)
        self.assertIn("strategy:", text)
        self.assertIn("fail-fast: false", text)
        self.assertIn("package: 7zip", text)
        self.assertIn("package: notepadplusplus", text)
        self.assertIn("cage run --dry-run", text)
        self.assertNotIn("docker build", text)
        self.assertNotIn("--requalify-cfw-runtime", text)
