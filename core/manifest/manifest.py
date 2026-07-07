"""Main Manifest class."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from .types import (
    RuntimeSpec, DependencySpec, InstallStep, FileMapping,
    SourceDeclaration, SuiteEntrypoint, FileAssociation,
    LaunchSpec,
)
from .helpers import (
    _object, _required_str, _optional_str, _list,
    _reject_unknown, _drop_none, _string_list,
    _tokenize_yaml, _load_strict_yaml,
)
from .constants import ROOT_FIELDS, SCHEMA_VERSION, LEGACY_SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS
from .errors import ManifestError
from core.compatibility import CompatibilityPolicyError, normalize_compatibility_policy
from core.profiles import ProfileError, apply_profiles
from core.modules import ModuleError, ModuleSpec, apply_modules

@dataclass(frozen=True)
class Manifest:
    schema_version: str
    name: str
    version: str
    runtime: RuntimeSpec
    profiles: list[str]
    modules: list[ModuleSpec]
    dependencies: list[DependencySpec]
    install: list[InstallStep]
    filesystem: list[FileMapping]
    launch: LaunchSpec
    provenance: dict[str, Any] = field(default_factory=dict)
    sources: list[SourceDeclaration] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    registry: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    exports: list[dict[str, Any]] = field(default_factory=list)
    entrypoints: list[SuiteEntrypoint] = field(default_factory=list)
    file_associations: list[FileAssociation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ManifestError("manifest root must be an object")
        _reject_unknown(data, ROOT_FIELDS, "manifest")
        try:
            data = apply_profiles(data)
            data = apply_modules(data)
        except (ProfileError, ModuleError) as exc:
            raise ManifestError(str(exc)) from exc
        schema = _required_str(data, "schemaVersion")
        if schema not in SUPPORTED_SCHEMA_VERSIONS:
            raise ManifestError(
                "schemaVersion must be one of: " + ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
            )
        if not isinstance(data.get("runtime"), dict):
            raise ManifestError("runtime must be an object")
        if not isinstance(data.get("launch"), dict):
            raise ManifestError("launch must be an object")

        provenance = _object(data.get("provenance", {}) or {}, "provenance")
        config = _object(data.get("config", {}) or {}, "config")
        raw_compatibility = _object(data.get("compatibility", {}) or {}, "compatibility")
        try:
            compatibility = normalize_compatibility_policy(
                config=config,
                compatibility=raw_compatibility,
            )
        except CompatibilityPolicyError as exc:
            raise ManifestError(str(exc)) from exc
        state = _object(data.get("state", {}) or {}, "state")
        profiles = _string_list(data.get("profiles", []), "profiles")
        modules = [ModuleSpec.from_dict(x, i) for i, x in enumerate(_list(data.get("modules", []), "modules"))]
        sources = [SourceDeclaration.from_dict(x, i) for i, x in enumerate(_list(data.get("sources", []), "sources"))]
        registry = _list(data.get("registry", []), "registry")
        exports = _list(data.get("exports", []), "exports")
        entrypoints = [SuiteEntrypoint.from_dict(x, i) for i, x in enumerate(_list(data.get("entrypoints", []), "entrypoints"))]
        _validate_entrypoint_ids(entrypoints)
        file_associations = [FileAssociation.from_dict(x, i) for i, x in enumerate(_list(data.get("fileAssociations", []), "fileAssociations"))]
        _validate_file_associations(file_associations, entrypoints)

        return cls(
            schema,
            _required_str(data, "name"),
            _required_str(data, "version"),
            RuntimeSpec.from_dict(data["runtime"]),
            profiles,
            modules,
            [DependencySpec.from_dict(x, i) for i, x in enumerate(_list(data.get("dependencies", []), "dependencies"))],
            [InstallStep.from_dict(x, i) for i, x in enumerate(_list(data.get("install", []), "install"))],
            [FileMapping.from_dict(x, i) for i, x in enumerate(_list(data.get("filesystem", []), "filesystem"))],
            LaunchSpec.from_dict(data["launch"]),
            provenance,
            sources,
            config,
            compatibility,
            registry,
            state,
            exports,
            entrypoints,
            file_associations,
        )

    def to_dict(self):
        return _drop_none({
            "schemaVersion": self.schema_version,
            "name": self.name,
            "version": self.version,
            "runtime": self.runtime.to_dict(),
            "profiles": self.profiles,
            "modules": [x.to_dict() for x in self.modules],
            "sources": [x.to_dict() for x in self.sources],
            "dependencies": [x.to_dict() for x in self.dependencies],
            "install": [x.to_dict() for x in self.install],
            "filesystem": [x.to_dict() for x in self.filesystem],
            "config": self.config,
            "compatibility": self.compatibility,
            "registry": self.registry,
            "launch": self.launch.to_dict(),
            "entrypoints": [x.to_dict() for x in self.entrypoints],
            "fileAssociations": [x.to_dict() for x in self.file_associations],
            "state": self.state,
            "exports": self.exports,
            "provenance": self.provenance,
        })



def _validate_entrypoint_ids(entrypoints: list[SuiteEntrypoint]) -> None:
    seen: set[str] = set()
    for index, entrypoint in enumerate(entrypoints):
        if entrypoint.id in seen:
            raise ManifestError(f"entrypoints[{index}].id is duplicated: {entrypoint.id}")
        seen.add(entrypoint.id)


def _validate_file_associations(associations: list[FileAssociation], entrypoints: list[SuiteEntrypoint]) -> None:
    ids = {entrypoint.id for entrypoint in entrypoints}
    if not ids and associations:
        raise ManifestError("fileAssociations require entrypoints")
    for index, association in enumerate(associations):
        if association.entrypoint not in ids:
            raise ManifestError(f"fileAssociations[{index}].entrypoint references unknown entrypoint: {association.entrypoint}")


def load_manifest(path: Path):
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ManifestError(f"file not found: {path}") from exc

    if suffix in {".yaml", ".yml"}:
        data = _load_strict_yaml(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    return Manifest.from_dict(data)
