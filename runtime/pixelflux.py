#!/usr/bin/env python3
"""Bounded, pod-local adapter for PixelFlux screenshot and input fallback.

This is an internal Cage runtime adapter. It is not a public control API: callers must
arrive through an approved typed skill or operator-controlled runtime command.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "http://127.0.0.1:5000/computer-use"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024
MAX_KEY_LENGTH = 128
MAX_TEXT_LENGTH = 4096
MAX_SCROLL_AMOUNT = 100
ALLOWED_ACTIONS = frozenset(
    {
        "mouse_move",
        "left_click",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
        "left_click_drag",
        "left_mouse_down",
        "left_mouse_up",
        "type",
        "key",
        "scroll",
        "cursor_position",
    }
)

ACTION_SCHEMAS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "mouse_move": (frozenset({"coordinate"}), frozenset({"coordinate"})),
    "left_click": (frozenset({"coordinate"}), frozenset({"coordinate"})),
    "right_click": (frozenset({"coordinate"}), frozenset({"coordinate"})),
    "middle_click": (frozenset({"coordinate"}), frozenset({"coordinate"})),
    "double_click": (frozenset({"coordinate"}), frozenset({"coordinate"})),
    "triple_click": (frozenset({"coordinate"}), frozenset({"coordinate"})),
    "left_click_drag": (
        frozenset({"start_coordinate", "coordinate"}),
        frozenset({"start_coordinate", "coordinate"}),
    ),
    "left_mouse_down": (frozenset(), frozenset()),
    "left_mouse_up": (frozenset(), frozenset()),
    "type": (frozenset({"text"}), frozenset({"text"})),
    "key": (frozenset({"text"}), frozenset({"text"})),
    "scroll": (
        frozenset({"scroll_direction", "scroll_amount", "coordinate"}),
        frozenset({"scroll_direction", "scroll_amount"}),
    ),
    "cursor_position": (frozenset(), frozenset()),
}


class PixelFluxClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        width: int = 1280,
        height: int = 800,
        timeout: float = 10.0,
    ) -> None:
        parsed = urllib.parse.urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.port != 5000
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "PixelFlux endpoint must be exactly HTTP loopback port 5000"
            )
        if parsed.path != "/computer-use":
            raise ValueError("PixelFlux endpoint path must be /computer-use")
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or not isinstance(height, int)
            or not 1 <= width <= 16384
            or not 1 <= height <= 16384
        ):
            raise ValueError(
                "framebuffer dimensions must be integers between 1 and 16384"
            )
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 60
        ):
            raise ValueError(
                "PixelFlux timeout must be finite and between 0 and 60 seconds"
            )
        self.endpoint = endpoint
        self.width = width
        self.height = height
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("PixelFlux request exceeded size limit")
        request = urllib.request.Request(
            self.endpoint,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"PixelFlux request failed: {exc.reason}") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("PixelFlux response exceeded size limit")
        try:
            result = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("PixelFlux returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise TypeError("PixelFlux returned a non-object response")
        return result

    def _validate_coordinate(self, value: Any, field: str = "coordinate") -> None:
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"{field} must be [x, y]")
        x, y = value
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
        ):
            raise TypeError(f"{field} values must be numbers")
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f"{field} falls outside {self.width}x{self.height}")

    def action(self, action: str, **parameters: Any) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"PixelFlux action is not allowed: {action}")
        allowed, required = ACTION_SCHEMAS[action]
        unknown = sorted(set(parameters) - allowed)
        missing = sorted(required - set(parameters))
        if unknown:
            raise ValueError(
                f"unexpected parameters for {action}: {', '.join(unknown)}"
            )
        if missing:
            raise ValueError(f"missing parameters for {action}: {', '.join(missing)}")
        for field in ("coordinate", "start_coordinate"):
            if field in parameters:
                self._validate_coordinate(parameters[field], field)
        if "text" in parameters:
            text = parameters["text"]
            limit = MAX_KEY_LENGTH if action == "key" else MAX_TEXT_LENGTH
            if not isinstance(text, str) or not text or len(text) > limit:
                raise ValueError(
                    f"text must be a non-empty string of at most {limit} characters"
                )
        if action == "scroll":
            direction = parameters.get("scroll_direction")
            amount = parameters.get("scroll_amount")
            if direction not in {"up", "down", "left", "right"}:
                raise ValueError("scroll_direction must be up, down, left, or right")
            if (
                isinstance(amount, bool)
                or not isinstance(amount, int)
                or not (1 <= amount <= MAX_SCROLL_AMOUNT)
            ):
                raise ValueError(
                    f"scroll_amount must be between 1 and {MAX_SCROLL_AMOUNT}"
                )
        return self._post({"action": action, **parameters})

    def screenshot(self, output: Path) -> None:
        response = self._post({"action": "screenshot"})
        data = response.get("data")
        if not isinstance(data, str):
            raise TypeError("PixelFlux screenshot response has no base64 data")
        try:
            png = base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise RuntimeError("PixelFlux screenshot data is not valid base64") from exc
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("PixelFlux screenshot is not a PNG")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(png)


def _client() -> PixelFluxClient:
    return PixelFluxClient(
        os.environ.get("CAGE_PIXELFLUX_URL", DEFAULT_ENDPOINT),
        width=int(os.environ.get("CAGE_DISPLAY_WIDTH", "1280")),
        height=int(os.environ.get("CAGE_DISPLAY_HEIGHT", "800")),
        timeout=float(os.environ.get("CAGE_PIXELFLUX_TIMEOUT", "10")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    shot = sub.add_parser("screenshot")
    shot.add_argument("output", type=Path)
    action = sub.add_parser("action")
    action.add_argument("name", choices=sorted(ALLOWED_ACTIONS))
    action.add_argument(
        "parameters", nargs="?", default="{}", help="bounded JSON object"
    )
    args = parser.parse_args(argv)

    try:
        client = _client()
        if args.command == "screenshot":
            client.screenshot(args.output)
            print(args.output)
        else:
            parameters = json.loads(args.parameters)
            if not isinstance(parameters, dict):
                raise ValueError("action parameters must be a JSON object")
            print(
                json.dumps(
                    client.action(args.name, **parameters), separators=(",", ":")
                )
            )
    except (TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"pixelflux-adapter: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
