#!/usr/bin/env python3
"""Record exact requested Chocolatey package versions from installed nuspecs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

SCHEMA = "cage.chocolatey-package-evidence/v0"


def _nuspecs(lib: Path, package_id: str):
    if not lib.is_dir():
        return []
    package_dirs = sorted(
        p for p in lib.iterdir() if p.is_dir() and p.name.casefold() == package_id.casefold()
    )
    if len(package_dirs) != 1:
        return []
    return sorted(package_dirs[0].rglob("*.nuspec"))


def _read_regular_bytes(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise OSError(f"not a regular package evidence file: {path}")
    with path.open("rb") as handle:
        before = path.stat(follow_symlinks=False)
        data = handle.read()
        after = path.stat(follow_symlinks=False)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise OSError(f"package evidence file changed while reading: {path}")
    return data


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _observed_package(lib: Path, package_id: str) -> dict | None:
    matches: list[tuple[str, Path, bytes]] = []
    nuspecs = _nuspecs(lib, package_id)
    for nuspec in nuspecs:
        try:
            nuspec_bytes = _read_regular_bytes(nuspec)
            root = ET.fromstring(nuspec_bytes)
            metadata = next((child for child in root if child.tag.rsplit("}", 1)[-1] == "metadata"), None)
            if metadata is None:
                continue
            values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in metadata}
            if values.get("id", "").casefold() == package_id.casefold() and values.get("version"):
                matches.append((values["version"], nuspec, nuspec_bytes))
        except (ET.ParseError, OSError):
            continue
    if len(nuspecs) != 1 or len(matches) != 1:
        return None
    version, nuspec, nuspec_bytes = matches[0]
    package_dir = nuspec.parent
    nupkgs = sorted(package_dir.glob("*.nupkg"))
    if len(nupkgs) != 1 or not nupkgs[0].is_file() or nupkgs[0].is_symlink():
        return None
    nupkg = nupkgs[0]
    try:
        nupkg_bytes = _read_regular_bytes(nupkg)
    except OSError:
        return None
    return {
        "id": package_id,
        "observed": True,
        "version": version,
        "nuspecPath": nuspec.relative_to(lib).as_posix(),
        "nuspecSha256": _sha256_bytes(nuspec_bytes),
        "nupkgPath": nupkg.relative_to(lib).as_posix(),
        "nupkgSha256": _sha256_bytes(nupkg_bytes),
    }


def collect(
    lib: Path, requested: list[str], install_rc: int, settle_rc: int, source_url: str
) -> tuple[dict, int]:
    observed = []
    query_rc = 0
    for package_id in requested:
        package = _observed_package(lib, package_id)
        if package is None:
            query_rc = 1
            package = {"id": package_id, "observed": False, "version": None}
        observed.append(package)
    passed = install_rc == 0 and settle_rc == 0 and query_rc == 0
    evidence = {
        "schemaVersion": SCHEMA,
        "status": "passed" if passed else "failed",
        "requested": observed,
        "sourceUrl": source_url,
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
    parser.add_argument("--source-url", required=True)
    args = parser.parse_args()
    try:
        requested = json.loads(args.requested)
        if not isinstance(requested, list) or not all(isinstance(item, str) and item for item in requested):
            raise ValueError("requested must be a list of non-empty strings")
        if not isinstance(args.source_url, str) or not args.source_url.strip():
            raise ValueError("source-url must be a non-empty string")
        evidence, rc = collect(
            args.lib, requested, args.install_rc, args.settle_rc, args.source_url
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.is_symlink():
            raise ValueError("output must not be a symlink")
        temporary = args.output.with_name(args.output.name + ".tmp")
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("temporary output already exists")
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(args.output)
        return rc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"package evidence query failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
