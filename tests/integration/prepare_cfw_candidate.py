"""Bind a CI-produced CFW candidate to explicit Cage proof recipes."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "core/chocolatey/assets/runtime-artifact.py"
spec = importlib.util.spec_from_file_location("cfw_runtime_artifact", HELPER)
assert spec and spec.loader
artifact = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = artifact
spec.loader.exec_module(artifact)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def one(root: Path, name: str) -> Path:
    found = list(root.rglob(name))
    if len(found) != 1 or not found[0].is_file():
        raise ValueError(f"expected exactly one {name}, found {len(found)}")
    return found[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    manifest_path = one(args.candidate, "cfw-runtime-manifest-wine-11.0.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sourceRevision") != args.source_revision:
        raise ValueError("candidate source revision mismatch")
    archive = one(args.candidate, manifest["archive"]["filename"])
    evidence_path = one(args.candidate, manifest["runtimeEvidence"]["filename"])
    if archive.stat().st_size != manifest["archive"]["bytes"]:
        raise ValueError("candidate archive size mismatch")
    if digest(archive) != manifest["archive"]["sha256"]:
        raise ValueError("candidate archive digest mismatch")
    if digest(evidence_path) != manifest["runtimeEvidence"]["sha256"]:
        raise ValueError("candidate evidence digest mismatch")
    image = manifest["wine"]["image"]
    candidate_mount = "/opt/cage-module-cache/cfw-candidate"
    profile = {
        "id": manifest["runtimeId"],
        "url": f"file://{candidate_mount}/{archive.name}",
        "evidenceUrl": f"file://{candidate_mount}/{evidence_path.name}",
        "manifestUrl": f"file://{candidate_mount}/{manifest_path.name}",
        "manifestSha256": digest(manifest_path),
        "wineImage": image,
        "wineVersions": [manifest["wine"]["version"]],
        "environment": manifest["interfaces"]["environment"],
        "sessionContract": manifest["sessionContract"],
    }
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    artifact.validate_records(profile, manifest, evidence, manifest["wine"]["version"], image)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    (args.output / "wine-image.txt").write_text(image + "\n", encoding="utf-8")
    for name, source in (
        ("lifecycle", ROOT / "tests/fixtures/chocolatey-bootstrap-smoke.cage.yaml"),
        ("7zip", ROOT / "recipes/7zip.cage.yaml"),
    ):
        recipe = yaml.safe_load(source.read_text(encoding="utf-8"))
        chocolatey = next(module for module in recipe["modules"] if module["type"] == "chocolatey")
        chocolatey["install"]["runtimeArtifact"] = profile
        if name == "7zip":
            recipe["launch"]["entrypoint"] = "C:/Program Files/7-Zip/7z.exe"
            recipe["launch"]["args"] = ["i"]
        # Cage accepts JSON directly. PyYAML's indentless-list output is outside
        # Cage's deliberately small YAML subset.
        (args.output / f"{name}.cage.json").write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifestSha256": profile["manifestSha256"], "wineImage": image,
                      "sourceRevision": manifest["sourceRevision"]}, sort_keys=True))


if __name__ == "__main__":
    main()
