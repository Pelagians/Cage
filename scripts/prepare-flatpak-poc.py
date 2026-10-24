#!/usr/bin/env python3
"""Acquire the pinned POC source, then reuse Cage's safe media staging."""
from pathlib import Path
import hashlib
import json
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.manifest import load_manifest
from core.media import stage_media


def main():
    manifest = load_manifest(ROOT / "recipes/notepadplusplus-portable.cage.yaml")
    source = manifest.sources[0]
    archive = ROOT / source.path
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix(".partial")
        with urllib.request.urlopen(source.url, timeout=120) as response, temporary.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 128 * 1024 * 1024:
                    raise ValueError("portable archive exceeds its download quota")
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != source.sha256:
            temporary.unlink()
            raise ValueError("portable application checksum mismatch")
        temporary.rename(archive)
    if archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != source.sha256:
        raise ValueError("portable application checksum mismatch")
    staged = ROOT / "sources/notepadplusplus-portable"
    if staged.exists():
        raise FileExistsError(f"source staging already exists; preserve or remove it explicitly before retrying: {staged}")
    result = stage_media(archive, name="notepadplusplus-portable", workspace=ROOT)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
