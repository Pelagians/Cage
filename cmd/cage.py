#!/usr/bin/env python3
"""Development shim for the packaged Cage CLI.

Installed users should call `cage`. Repo-local development can keep using
`python3 cmd/cage.py ...`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cage.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
