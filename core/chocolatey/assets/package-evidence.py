#!/usr/bin/env python3
"""Record exact requested Chocolatey package versions from installed nuspecs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

SCHEMA = "cage.chocolatey-package-evidence/v0"


def _nuspecs(lib: Path, package_id: str):
    if not lib.is_dir():
        return []
    package_dir = next((p for p in lib.iterdir() if p.is_dir() and p.name.casefold() == package_id.casefold()), None)
    if package_dir is None:
        return []
    return sorted(package_dir.rglob("*.nuspec"))


def collect(lib: Path, requested: list[str], install_rc: int, settle_rc: int) -> tuple[dict, int]:
    observed = []
    query_rc = 0
    for package_id in requested:
        version = None
        for nuspec in _nuspecs(lib, package_id):
            try:
                root = ET.parse(nuspec).getroot()
                metadata = next((child for child in root if child.tag.rsplit("}", 1)[-1] == "metadata"), None)
                if metadata is None:
                    continue
                values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in metadata}
                if values.get("id", "").casefold() == package_id.casefold() and values.get("version"):
                    version = values["version"]
                    break
            except (ET.ParseError, OSError):
                continue
        if version is None:
            query_rc = 1
        observed.append({"id": package_id, "observed": version is not None, "version": version})
    passed = install_rc == 0 and settle_rc == 0 and query_rc == 0
    evidence = {
        "schemaVersion": SCHEMA,
        "status": "passed" if passed else "failed",
        "requested": observed,
        "checks": {"requestedPackages": passed},
        "returnCodes": {"install": install_rc, "settle": settle_rc, "query": query_rc},
    }
    return evidence, 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requested", required=True)
    parser.add_argument("--install-rc", type=int, required=True)
    parser.add_argument("--settle-rc", type=int, required=True)
    args = parser.parse_args()
    try:
        requested = json.loads(args.requested)
        if not isinstance(requested, list) or not all(isinstance(item, str) and item for item in requested):
            raise ValueError("requested must be a list of non-empty strings")
        evidence, rc = collect(args.lib, requested, args.install_rc, args.settle_rc)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return rc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"package evidence query failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
