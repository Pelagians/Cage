"""Verify and safely extract a CFW prepared-runtime artifact.

This file is embedded into Cage's generated build script so the consumer uses
one executable verification path in tests and inside the runtime container.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
from urllib.parse import urlparse


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^ghcr\.io/pelagians/cage-wine@sha256:[0-9a-f]{64}$")
RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
WINE_VERSION_RE = re.compile(r"^wine-[0-9]+(?:\.[0-9]+){1,2}$")
UNSAFE_SOURCE_RE = re.compile(r"[\x00-\x1f\x7f$`;&|<>]")
REQUIRED_INTERFACE = "chocolatey"
MAX_MEMBERS = 250_000
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024 * 1024


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source(field: str, value: str) -> None:
    _require(UNSAFE_SOURCE_RE.search(value) is None, f"runtime profile {field} contains unsafe characters")
    parsed = urlparse(value)
    if parsed.scheme == "https":
        _require(bool(parsed.hostname) and parsed.username is None and parsed.password is None,
                 f"runtime profile {field} must be a plain HTTPS URL")
        return
    if parsed.scheme == "file":
        _require(parsed.netloc in ("", "localhost") and parsed.path.startswith("/"),
                 f"runtime profile {field} must use an absolute file URL")
        return
    _require(value.startswith("/"),
             f"runtime profile {field} must use https://, file://, or an absolute path")


def validate_profile(profile: dict[str, Any]) -> None:
    runtime_id = profile.get("id")
    _require(isinstance(runtime_id, str) and RUNTIME_ID_RE.fullmatch(runtime_id) is not None,
             "runtime profile id is missing or unsafe")
    image = profile.get("wineImage")
    _require(isinstance(image, str) and IMAGE_RE.fullmatch(image) is not None,
             "runtime profile Wine image is not digest-pinned")
    versions = profile.get("wineVersions")
    _require(isinstance(versions, list) and bool(versions) and all(
        isinstance(value, str) and WINE_VERSION_RE.fullmatch(value) is not None for value in versions
    ), "runtime profile Wine versions are invalid")
    for field in ("url", "evidenceUrl", "manifestUrl"):
        value = profile.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"runtime profile {field} is missing")
        _validate_source(field, value)
    manifest_digest = profile.get("manifestSha256")
    _require(isinstance(manifest_digest, str) and SHA256_RE.fullmatch(manifest_digest) is not None,
             "runtime profile manifest digest is invalid")
    _require(profile.get("environment") == {"WINEDLLOVERRIDES": ""},
             "runtime profile environment is missing or invalid")


def _validate_bound_fields(record: dict[str, Any], label: str) -> None:
    revision = record.get("sourceRevision")
    contract_digest = record.get("contractSha256")
    installer = record.get("installerSha256")
    inputs = record.get("runtimeInputsSha256")
    wine = record.get("wine")
    _require(isinstance(revision, str) and REVISION_RE.fullmatch(revision) is not None,
             f"{label} sourceRevision is missing or invalid")
    _require(isinstance(contract_digest, str) and SHA256_RE.fullmatch(contract_digest) is not None,
             f"{label} contractSha256 is missing or invalid")
    _require(isinstance(installer, str) and SHA256_RE.fullmatch(installer) is not None,
             f"{label} installerSha256 is missing or invalid")
    _require(isinstance(inputs, str) and SHA256_RE.fullmatch(inputs) is not None,
             f"{label} runtimeInputsSha256 is missing or invalid")
    _require(isinstance(wine, dict), f"{label} wine binding is missing")
    _require(isinstance(wine.get("image"), str) and IMAGE_RE.fullmatch(wine["image"]) is not None,
             f"{label} Wine image is missing or invalid")
    _require(isinstance(wine.get("version"), str) and wine["version"],
             f"{label} Wine version is missing")
    _require(wine.get("architecture") == "win64", f"{label} Wine architecture must be win64")


def validate_manifest(profile: dict[str, Any], manifest: dict[str, Any]) -> None:
    validate_profile(profile)
    _require(manifest.get("schemaVersion") == "cfw.prepared-runtime-manifest/v1",
             "unexpected CFW runtime manifest schema")
    _require(manifest.get("contract") == "cfw.compatibility-contract/v3",
             "unexpected CFW runtime compatibility contract")
    _require(manifest.get("status") == "passed", "CFW runtime manifest status is not passed")
    _require(manifest.get("runtimeId") == profile["id"], "CFW runtime manifest identity mismatch")
    archive = manifest.get("archive")
    evidence = manifest.get("runtimeEvidence")
    _require(isinstance(archive, dict), "CFW runtime manifest archive binding is missing")
    _require(isinstance(evidence, dict), "CFW runtime manifest evidence binding is missing")
    for label, binding in (("archive", archive), ("evidence", evidence)):
        digest = binding.get("sha256")
        filename = binding.get("filename")
        _require(isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None,
                 f"CFW runtime manifest {label} digest is invalid")
        _require(isinstance(filename, str) and filename and Path(filename).name == filename,
                 f"CFW runtime manifest {label} filename is invalid")
    _require(isinstance(archive.get("bytes"), int) and archive["bytes"] > 0,
             "CFW runtime manifest archive size is invalid")
    proofs = manifest.get("requiredProofs")
    _require(
        isinstance(proofs, list) and bool(proofs)
        and all(isinstance(name, str) and name for name in proofs)
        and len(set(proofs)) == len(proofs),
        "CFW runtime manifest requiredProofs is missing or invalid",
    )
    interfaces = manifest.get("interfaces")
    if not isinstance(interfaces, dict):
        raise ValueError("CFW runtime manifest interfaces are missing")
    chocolatey = interfaces.get(REQUIRED_INTERFACE)
    if not isinstance(chocolatey, dict):
        raise ValueError("CFW runtime manifest Chocolatey interface is missing")
    windows_path = chocolatey.get("windowsPath")
    prefix_path = chocolatey.get("prefixRelativePath")
    if not isinstance(windows_path, str):
        raise ValueError("CFW runtime manifest Chocolatey Windows path is invalid")
    if not isinstance(prefix_path, str):
        raise ValueError("CFW runtime manifest Chocolatey prefix path is invalid")
    _require(windows_path.startswith("C:\\") and "\n" not in windows_path,
             "CFW runtime manifest Chocolatey Windows path is invalid")
    _require(bool(_member_parts(prefix_path)),
             "CFW runtime manifest Chocolatey prefix path is invalid")
    windows = PureWindowsPath(windows_path)
    _require(
        windows.drive == "C:" and windows.root == "\\"
        and all(part not in (".", "..") for part in windows.parts[1:]),
        "CFW runtime manifest Chocolatey Windows path is invalid",
    )
    expected_prefix = PurePosixPath("drive_c", *windows.parts[1:]).as_posix()
    _require(prefix_path == expected_prefix,
             "CFW runtime manifest Chocolatey interface representations do not match")
    _require(interfaces.get("environment") == profile["environment"],
             "CFW runtime manifest environment does not match profile")
    _validate_bound_fields(manifest, "manifest")


def validate_records(
    profile: dict[str, Any],
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    observed_wine: str,
    actual_image: str,
) -> None:
    validate_manifest(profile, manifest)
    _require(evidence.get("schemaVersion") == "cfw.runtime-build/v2",
             "unexpected CFW runtime evidence schema")
    _require(evidence.get("contract") == manifest.get("contract"),
             "CFW runtime evidence contract does not match manifest")
    _require(evidence.get("provider") == "cfw-chocolatey-runtime", "unexpected CFW runtime provider")
    _require(evidence.get("status") == "passed", "CFW runtime evidence status is not passed")
    _require(evidence.get("runtimeId") == profile["id"], "CFW runtime evidence identity mismatch")
    _validate_bound_fields(evidence, "evidence")
    for field in ("sourceRevision", "contractSha256", "installerSha256", "runtimeInputsSha256", "wine"):
        _require(evidence[field] == manifest[field], f"CFW runtime evidence {field} does not match manifest")
    checks = evidence.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("CFW runtime evidence checks are missing")
    required = manifest["requiredProofs"]
    _require(set(checks) == set(required), "CFW runtime evidence checks do not match manifest requiredProofs")
    missing = sorted(name for name in required if checks.get(name) is not True)
    _require(not missing, "CFW runtime evidence is missing required proofs: " + ", ".join(missing))
    _require(observed_wine == evidence["wine"]["version"],
             f"CFW runtime evidence does not declare compatibility with {observed_wine}")
    _require(observed_wine in profile["wineVersions"],
             f"CFW runtime profile does not declare compatibility with {observed_wine}")
    _require(manifest["wine"]["image"] == profile["wineImage"], "CFW runtime manifest Wine image mismatch")
    _require(actual_image == profile["wineImage"], "CFW runtime Wine image mismatch")


def _member_parts(name: str) -> tuple[str, ...]:
    path = PurePosixPath(name)
    _require(not path.is_absolute(), f"unsafe path in CFW runtime archive: {name}")
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if not parts:
        _require(path == PurePosixPath("."), f"unsafe path in CFW runtime archive: {name}")
        return ()
    _require(".." not in parts, f"unsafe path in CFW runtime archive: {name}")
    return parts


def _inside(root: Path, path: Path, message: str) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(message) from exc


def extract_prepared_prefix(
    archive_path: Path,
    prefix: Path,
    *,
    required_files: tuple[str, ...] = (),
) -> None:
    archive_path = Path(archive_path)
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=".cage-cfw-", dir=prefix.parent))
    staging = staging_parent / "prefix"
    staging.mkdir()
    promotion_completed = False
    pending_symlinks: list[tuple[tarfile.TarInfo, Path]] = []
    directory_modes: list[tuple[Path, int]] = []
    seen: set[tuple[str, ...]] = set()
    member_count = 0
    total_size = 0
    try:
        with tarfile.open(archive_path, "r|gz") as archive:
            for member in archive:
                member_count += 1
                _require(member_count <= MAX_MEMBERS, "CFW runtime archive has too many members")
                parts = _member_parts(member.name)
                if not parts:
                    _require(member.isdir(), "CFW runtime archive root entry must be a directory")
                    continue
                if parts[0] == ".cfw":
                    allowed_metadata = parts == (".cfw",) and member.isdir()
                    allowed_evidence = parts == (".cfw", "runtime.json") and member.isfile()
                    _require(allowed_metadata or allowed_evidence,
                             f"reserved Cage metadata path in CFW runtime archive: {member.name}")
                _require(parts not in seen, f"duplicate path in CFW runtime archive: {member.name}")
                seen.add(parts)
                target = staging.joinpath(*parts)
                _inside(staging, target, f"unsafe path in CFW runtime archive: {member.name}")
                if member.islnk():
                    raise ValueError(f"hardlinks are not supported in CFW runtime archive: {member.name}")
                if member.issym():
                    link = PurePosixPath(member.linkname)
                    _require(bool(member.linkname) and not link.is_absolute(),
                             f"unsafe symlink in CFW runtime archive: {member.name} -> {member.linkname}")
                    resolved = target.parent.joinpath(*link.parts)
                    _inside(staging, resolved,
                            f"unsafe symlink in CFW runtime archive: {member.name} -> {member.linkname}")
                    pending_symlinks.append((member, target))
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    directory_modes.append((target, member.mode & 0o777))
                    continue
                _require(member.isfile(), f"unsupported archive member: {member.name}")
                total_size += member.size
                _require(total_size <= MAX_UNCOMPRESSED_BYTES, "CFW runtime archive is too large")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"unable to read CFW runtime archive member: {member.name}")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)

        for member, target in sorted(pending_symlinks, key=lambda item: len(item[1].parts)):
            _require(not target.exists() and not target.is_symlink(),
                     f"symlink path conflicts with extracted content: {member.name}")
            parent = target.parent
            while parent != staging:
                _require(not parent.is_symlink(), f"unsafe symlink ancestor in CFW runtime archive: {member.name}")
                parent = parent.parent
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(member.linkname)

        _require((staging / "drive_c").is_dir(), "CFW prepared prefix is missing drive_c")
        for relative in required_files:
            parts = _member_parts(relative)
            required = staging.joinpath(*parts)
            current = staging
            for part in parts:
                current = current / part
                _require(not current.is_symlink(),
                         f"CFW prepared prefix interface path must not contain symlinks: {relative}")
            _require(required.is_file() and required.stat().st_size > 0,
                     f"CFW prepared prefix is missing required interface file: {relative}")
        for directory, mode in sorted(directory_modes, key=lambda item: len(item[0].parts), reverse=True):
            directory.chmod(mode)
        backup = staging_parent / "previous-prefix"
        had_previous = prefix.exists() or prefix.is_symlink()
        if had_previous:
            os.replace(prefix, backup)
        try:
            os.replace(staging, prefix)
            promotion_completed = True
        except Exception:
            if had_previous and backup.exists() and not prefix.exists() and not prefix.is_symlink():
                os.replace(backup, prefix)
            raise
    finally:
        backup = staging_parent / "previous-prefix"
        if promotion_completed or not backup.exists():
            shutil.rmtree(staging_parent, ignore_errors=True)


def _manifest_fields(profile_path: Path, manifest_path: Path) -> None:
    profile = _read_json(profile_path)
    manifest = _read_json(manifest_path)
    validate_manifest(profile, manifest)
    print(manifest["archive"]["sha256"])
    print(manifest["runtimeEvidence"]["sha256"])
    print(manifest["archive"]["bytes"])
    print(manifest["interfaces"][REQUIRED_INTERFACE]["windowsPath"])
    print(manifest["interfaces"][REQUIRED_INTERFACE]["prefixRelativePath"])


def _profile_fields(profile_path: Path) -> None:
    profile = _read_json(profile_path)
    validate_profile(profile)
    for field in ("id", "url", "evidenceUrl", "manifestUrl", "manifestSha256", "wineImage"):
        print(profile[field])
    print(",".join(profile["wineVersions"]))


def _verify_extract(profile_path: Path, manifest_path: Path, evidence_path: Path, archive_path: Path, prefix: Path) -> None:
    profile = _read_json(profile_path)
    manifest = _read_json(manifest_path)
    evidence = _read_json(evidence_path)
    archive_binding = manifest.get("archive") or {}
    evidence_binding = manifest.get("runtimeEvidence") or {}
    _require(_sha256(archive_path) == archive_binding.get("sha256") and archive_path.stat().st_size == archive_binding.get("bytes"),
             "CFW runtime archive does not match manifest")
    _require(_sha256(evidence_path) == evidence_binding.get("sha256"),
             "CFW runtime evidence does not match manifest")
    observed_wine = subprocess.run(["wine", "--version"], text=True, capture_output=True, check=True).stdout.strip()
    validate_records(profile, manifest, evidence, observed_wine, os.environ.get("CAGE_RUNTIME_IMAGE", ""))
    chocolatey_path = manifest["interfaces"][REQUIRED_INTERFACE]["prefixRelativePath"]
    extract_prepared_prefix(archive_path, prefix, required_files=(chocolatey_path,))


def main(argv: list[str]) -> int:
    try:
        command = argv[1]
        if command == "profile-fields" and len(argv) == 3:
            _profile_fields(Path(argv[2]))
        elif command == "manifest-fields" and len(argv) == 4:
            _manifest_fields(Path(argv[2]), Path(argv[3]))
        elif command == "verify-extract" and len(argv) == 7:
            _verify_extract(*(Path(value) for value in argv[2:]))
        else:
            raise ValueError("invalid runtime-artifact helper invocation")
    except (KeyError, OSError, ValueError, json.JSONDecodeError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"[cage] ERROR: {exc}", file=sys.stderr)
        return 66
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
