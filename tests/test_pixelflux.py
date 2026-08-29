from __future__ import annotations

import unittest

from runtime.pixelflux import ALLOWED_ACTIONS, PixelFluxClient


class PixelFluxBoundaryTests(unittest.TestCase):
    def test_endpoint_must_be_loopback_computer_use(self):
        for endpoint in (
            "http://10.0.0.2:5000/computer-use",
            "https://127.0.0.1:5000/computer-use",
            "http://127.0.0.1:5000/admin",
            "http://127.0.0.1:22/computer-use",
            "http://127.0.0.1/computer-use",
            "http://127.0.0.1:5000/computer-use?admin=1",
            "http://localhost:5000/computer-use",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                PixelFluxClient(endpoint)

    def test_constructor_bounds_dimensions_and_timeout(self):
        for kwargs in (
            {"width": True},
            {"width": 1_000_000},
            {"height": False},
            {"timeout": 0},
            {"timeout": float("inf")},
            {"timeout": 61},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PixelFluxClient(**kwargs)

    def test_coordinates_are_bounded_to_framebuffer(self):
        client = PixelFluxClient(width=1280, height=800)
        for coordinate in ([-1, 0], [1280, 0], [0, 800], [False, 2]):
            with (
                self.subTest(coordinate=coordinate),
                self.assertRaises((ValueError, TypeError)),
            ):
                client.action("mouse_move", coordinate=coordinate)

    def test_dangerous_or_unbounded_actions_are_not_available(self):
        self.assertNotIn("shell", ALLOWED_ACTIONS)
        self.assertNotIn("upload", ALLOWED_ACTIONS)
        client = PixelFluxClient()
        with self.assertRaises(ValueError):
            client.action("shell", text="id")
        with self.assertRaises(ValueError):
            client.action("type", text="x" * 4097)


if __name__ == "__main__":
    unittest.main()
