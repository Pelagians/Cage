"""Source integrity checks for Cage recipes."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.manifest import Manifest
from core.media import SOURCE_POLICY_SCHEMA_VERSION, audit_source_path

SOURCE_INTEGRITY_SCHEMA_VERSION = "cage.source-integrity/v0"
_SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_REMOTE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def verify_manifest_sources(manifest: Manifest, *, workspace: Path | str | None = None) -> dict[str, Any]:
    """Verify local source presence and hashes for a manifest.

    v0 build execution consumes local files from the workspace mount. Remote
    URLs are recorded as source declarations but are not downloaded here.
    """
    workspace_path = Path(workspace or Path.cwd()).resolve()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def add_item(
        *,
        location: str,
        usage: str,
        source: str | None,
        expected_sha256: str | None = None,
        require_local: bool = True,
        source_id: str | None = None,
        source_type: str | None = None,
        source_policy: str | None = None,
    ) -> None:
        if not source:
            error = f"{location}: source is missing"
            item = {
                "location": location,
                "usage": usage,
                "status": "missing-source",
                "valid": False,
                "error": error,
            }
            items.append(item)
            errors.append(error)
            return

        item: dict[str, Any] = {
            "location": location,
            "usage": usage,
            "source": source,
            "valid": True,
        }
        if source_id:
            item["sourceId"] = source_id
        if source_type:
            item["sourceType"] = source_type
        if source_policy:
            item["sourcePolicy"] = source_policy
        sha_error = _validate_expected_sha(location, expected_sha256)
        if expected_sha256:
            item["expectedSha256"] = expected_sha256
        if sha_error:
            item["valid"] = False
            item["status"] = "invalid-sha256"
            item["error"] = sha_error
            items.append(item)
            errors.append(sha_error)
            return

        if is_remote_source(source):
            item["status"] = "remote"
            item["verified"] = False
            if require_local:
                error = f"{location}: remote source must be materialized locally for v0 build: {source}"
                item["valid"] = False
                item["error"] = error
                errors.append(error)
            else:
                warning = f"{location}: remote source was not fetched by source verifier: {source}"
                item["warning"] = warning
                warnings.append(warning)
            items.append(item)
            return

        try:
            resolved = resolve_source_path(source, workspace_path)
        except ValueError as exc:
            item.update({"valid": False, "status": "unsafe-path", "error": f"{location}: {exc}"})
            errors.append(item["error"])
            items.append(item)
            return
        item["resolvedPath"] = str(resolved)
        item["exists"] = resolved.exists()
        if not resolved.exists():
            error = f"{location}: missing local source: {resolved}"
            item["valid"] = False
            item["status"] = "missing"
            item["error"] = error
            items.append(item)
            errors.append(error)
            return

        if expected_sha256:
            if not resolved.is_file():
                error = f"{location}: sha256 verification requires a file source: {resolved}"
                item["valid"] = False
                item["status"] = "unsupported-directory-hash"
                item["error"] = error
                items.append(item)
                errors.append(error)
                return
            actual = sha256_file(resolved)
            item["sha256"] = actual
            if actual.lower() != expected_sha256.lower():
                error = f"{location}: sha256 mismatch for {resolved}: expected {expected_sha256}, got {actual}"
                item["valid"] = False
                item["status"] = "hash-mismatch"
                item["error"] = error
                items.append(item)
                errors.append(error)
                return
            item["status"] = "verified"
            item["verified"] = True
        else:
            item["status"] = "present"
            item["verified"] = False
            warning = f"{location}: source is present but no sha256 was declared"
            item["warning"] = warning
            warnings.append(warning)
        items.append(item)

    for index, source in enumerate(manifest.sources):
        # For files-type sources, use path; for others, use url
        ref = source.path or source.url or source.source
        add_item(
            location=f"sources[{index}]",
            usage="declared-source",
            source=str(ref) if ref is not None else None,
            expected_sha256=source.sha256,
            require_local=False,
            source_id=source.id,
            source_type=source.type,
            source_policy=source.policy,
        )

    # File mappings are inputs too, even when they have no top-level declaration.
    for index, module in enumerate(manifest.modules):
        if module.type == "files":
            for mapping_index, mapping in enumerate(module.mappings or []):
                add_item(
                    location=f"modules[{index}].mappings[{mapping_index}].source",
                    usage="module:files",
                    source=mapping["source"],
                    expected_sha256=mapping.get("sha256"),
                )
        if module.type == "registry" and module.file:
            add_item(location=f"modules[{index}].file", usage="module:registry",
                     source=module.file, expected_sha256=module.sha256)
        if module.type == "script" and module.file:
            add_item(location=f"modules[{index}].file", usage="module:script", source=module.file,
                     expected_sha256=module.sha256)
        if module.type == "dll" and module.install:
            add_item(location=f"modules[{index}].install.source", usage="module:dll",
                     source=module.install["source"], expected_sha256=module.install["sha256"])
        if module.type == "iso" and module.action == "mount":
            add_item(location=f"modules[{index}].mountPath", usage="module:iso-host-mount",
                     source=module.mount_path)

    # Check modules for source references
    for index, module in enumerate(manifest.modules):
        if module.type == "chocolatey":
            # CFW assets are resolved and checksum-verified through the detached
            # prepared-runtime manifest, not as recipe-local sources.
            continue
        if hasattr(module, 'source') and module.source:
            if module.type == "install" and (re.match(r"^[C-Yc-y]:/", module.source) or module.source.startswith("/work/")):
                continue
            add_item(
                location=f"modules[{index}].source",
                usage=f"module:{module.type}",
                source=module.source,
                expected_sha256=getattr(module, 'sha256', None),
                require_local=True,
            )

    summary = {
        "checked": len(items),
        "local": sum(1 for item in items if item.get("resolvedPath")),
        "remote": sum(1 for item in items if item.get("status") == "remote"),
        "missing": sum(1 for item in items if item.get("status") == "missing"),
        "verified": sum(1 for item in items if item.get("status") == "verified"),
        "warnings": len(warnings),
        "errors": len(errors),
    }
    return {
        "schemaVersion": SOURCE_INTEGRITY_SCHEMA_VERSION,
        "workspace": str(workspace_path),
        "valid": not errors,
        "summary": summary,
        "items": items,
        "errors": errors,
        "warnings": warnings,
    }


def is_remote_source(source: str) -> bool:
    return bool(_REMOTE_RE.match(source)) and not source.startswith("file://")


def strip_file_scheme(source: str) -> str:
    return source[len("file://"):] if source.startswith("file://") else source


def resolve_source_path(source: str, workspace: Path | str | None = None) -> Path:
    raw = strip_file_scheme(source)
    path = Path(raw)
    if path.is_absolute():
        return path
    if ".." in path.parts:
        raise ValueError(f"workspace source may not escape its root: {source}")
    return Path(workspace or Path.cwd()).resolve() / path


def container_source_path(source: str, *, workspace_mount: str = "/workspace") -> str:
    """Return the path a source reference should use inside the build container."""
    if is_remote_source(source):
        return source
    raw = strip_file_scheme(source)
    if Path(raw).is_absolute():
        if raw.startswith(("/workspace/", "/work/")) and ".." not in Path(raw).parts:
            return raw
        raise ValueError(f"absolute recipe input must be in /workspace or /work: {source}")
    if ".." in Path(raw).parts:
        raise ValueError(f"workspace source may not escape its root: {source}")
    return f"{workspace_mount.rstrip('/')}/{raw}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_expected_sha(location: str, expected_sha256: str | None) -> str | None:
    if expected_sha256 is None:
        return None
    if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256):
        return f"{location}: sha256 must be 64 hexadecimal characters"
    return None


def audit_manifest_sources(manifest: Manifest, *, workspace: Path | str | None = None) -> dict[str, Any]:
    """Audit manifest source paths for policy-blocked artifact names.

    This is a preflight safety check. It scans local path names only and does
    not read source file contents, so secrets/product keys in local media cannot
    leak into the audit report.
    """
    workspace_path = Path(workspace or Path.cwd()).resolve()
    items: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[Path] = set()

    def add_item(*, location: str, usage: str, source: str | None, source_id: str | None = None, source_type: str | None = None, source_policy: str | None = None) -> None:
        item: dict[str, Any] = {
            "location": location,
            "usage": usage,
            "valid": True,
        }
        if source_id:
            item["sourceId"] = source_id
        if source_type:
            item["sourceType"] = source_type
        if source_policy:
            item["sourcePolicy"] = source_policy
        if not source:
            item.update({"valid": False, "status": "missing-source", "error": f"{location}: source is missing"})
            errors.append(item["error"])
            items.append(item)
            return
        item["source"] = source
        if is_remote_source(source):
            item.update({"status": "remote", "audited": False})
            warning = f"{location}: remote source was not audited locally: {source}"
            item["warning"] = warning
            warnings.append(warning)
            items.append(item)
            return
        try:
            resolved = resolve_source_path(source, workspace_path)
        except ValueError as exc:
            item.update({"valid": False, "status": "unsafe-path", "error": f"{location}: {exc}"})
            errors.append(item["error"])
            items.append(item)
            return
        item["resolvedPath"] = str(resolved)
        if not resolved.exists():
            item.update({"valid": False, "status": "missing", "error": f"{location}: missing local source: {resolved}"})
            errors.append(item["error"])
            items.append(item)
            return
        resolved_key = resolved.resolve()
        if resolved_key in seen:
            item.update({"status": "duplicate", "audited": False})
            items.append(item)
            return
        seen.add(resolved_key)
        audit = audit_source_path(resolved, location=location)
        item.update({
            "status": "audited" if audit["valid"] else "policy-blocked",
            "audited": True,
            "findingCount": audit["summary"]["findings"],
            "blockedCount": audit["summary"]["blocked"],
            "valid": audit["valid"],
        })
        for finding in audit["findings"]:
            findings.append({
                **finding,
                "usage": usage,
                "source": source,
                **({"sourceId": source_id} if source_id else {}),
            })
        for error in audit["errors"]:
            errors.append(f"{location}: {error}")
        items.append(item)

    for index, source in enumerate(manifest.sources):
        # For files-type sources, use path; for others, use url
        ref = source.path or source.url or source.source
        add_item(
            location=f"sources[{index}]",
            usage="declared-source",
            source=str(ref) if ref is not None else None,
            source_id=source.id,
            source_type=source.type,
            source_policy=source.policy,
        )

    for index, module in enumerate(manifest.modules):
        if module.type == "files":
            for mapping_index, mapping in enumerate(module.mappings or []):
                add_item(
                    location=f"modules[{index}].mappings[{mapping_index}].source",
                    usage="module:files",
                    source=mapping["source"],
                )
        if module.type == "registry" and module.file:
            add_item(location=f"modules[{index}].file", usage="module:registry", source=module.file)
        if module.type == "script" and module.file:
            add_item(location=f"modules[{index}].file", usage="module:script", source=module.file)
        if module.type == "dll" and module.install:
            add_item(location=f"modules[{index}].install.source", usage="module:dll", source=module.install["source"])
        if module.type == "iso" and module.action == "mount":
            add_item(location=f"modules[{index}].mountPath", usage="module:iso-host-mount", source=module.mount_path)

    # Check modules for source references
    for index, module in enumerate(manifest.modules):
        if module.type == "chocolatey":
            # CFW assets are resolved and checksum-verified through the detached
            # prepared-runtime manifest, not as recipe-local sources.
            continue
        if hasattr(module, 'source') and module.source:
            if module.type == "install" and (re.match(r"^[C-Yc-y]:/", module.source) or module.source.startswith("/work/")):
                continue
            add_item(
                location=f"modules[{index}].source",
                usage=f"module:{module.type}",
                source=module.source,
            )

    blocked = sum(1 for finding in findings if finding.get("severity") == "blocked")
    summary = {
        "checked": len(items),
        "audited": sum(1 for item in items if item.get("audited")),
        "findings": len(findings),
        "blocked": blocked,
        "warnings": len(warnings),
        "errors": len(errors),
    }
    return {
        "schemaVersion": SOURCE_POLICY_SCHEMA_VERSION,
        "workspace": str(workspace_path),
        "valid": not errors and blocked == 0,
        "summary": summary,
        "items": items,
        "findings": findings,
        "errors": errors,
        "warnings": warnings,
    }
