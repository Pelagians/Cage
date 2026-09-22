#!/usr/bin/env python3
"""Regression tests for the real-window smoke gate."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("shell_check", Path(__file__).with_name("verify-shell-session.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GeometryGateTests(unittest.TestCase):
    def setUp(self):
        self.area = dict(x=0, y=0, width=1920, height=1080)
        self.view = dict(self.area, type="normal", parent_id=None, app_id="test-app",
                         title="Test App", decoration="full", titlebar_visible=True,
                         maximized=True, fullscreen=False, minimized=False, tiled=False, region="")
        self.state = dict(views=[self.view], outputs=[dict(usable_area=self.area)])
        self.health = dict(adapter_connected=True, layoutd="healthy", reconciliation="healthy", managed_windows=1)

    def test_accepts_observed_maximized_app(self):
        module.verify(self.state, self.health, "test-app")

    def test_rejects_green_status_with_stale_geometry(self):
        self.view["width"] = 800
        with self.assertRaises(AssertionError):
            module.verify(self.state, self.health, "test-app")

    def test_rejects_fullscreen_and_missing_titlebar(self):
        for changes in (dict(fullscreen=True), dict(titlebar_visible=False)):
            with self.subTest(changes=changes):
                view = self.view | changes
                with self.assertRaises(AssertionError):
                    module.verify(self.state | dict(views=[view]), self.health, "test-app")

    def test_rejects_wrong_application(self):
        with self.assertRaises(AssertionError):
            module.verify(self.state, self.health, "unrelated")


if __name__ == "__main__":
    unittest.main()
