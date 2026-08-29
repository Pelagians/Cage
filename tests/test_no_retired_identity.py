from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = "v" + "ic"
PATTERN = re.compile(rf"(?<![a-z]){OLD}(?![a-z])", re.IGNORECASE)
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache"}


class RetiredIdentityTests(unittest.TestCase):
    def test_retired_identity_is_absent_from_paths_and_text(self):
        hits: list[str] = []
        for path in ROOT.rglob("*"):
            if any(part in SKIP for part in path.parts):
                continue
            relative = path.relative_to(ROOT)
            if PATTERN.search(str(relative)):
                hits.append(str(relative))
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if PATTERN.search(text):
                    hits.append(str(relative))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
