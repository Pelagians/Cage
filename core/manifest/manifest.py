"""Simplified Manifest for module-first architecture.

This is the new Manifest that parses modules directly without expansion.
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .errors import ManifestError
from .helpers import _reject_unknown, _required_str, _optional_str, _drop_none, _load_strict_yaml
from .constants import (
    ROOT_FIELDS,
    RUNTIME_FIELDS,
    BUILD_FIELDS,
    LAUNCH_FIELDS,
    SOURCE_FIELDS,
    SUPPORTED_SCHEMA_VERSIONS,
    ALLOWED_RUNTIME_NETWORK_MODES,
    ALLOWED_SOURCE_TYPES,
    ALLOWED_SOURCE_POLICIES,
)
from ..compatibility import CompatibilityPolicyError, normalize_compatibility_policy
from ..modules import parse_module, ModuleBase, ModuleError


def load_manifest(path: Path) -> Manifest:
    """Load a manifest from a file (YAML or JSON).
    
    Args:
        path: Path to the manifest file
    
    Returns:
        Parsed Manifest instance
    """
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
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be an object")
    return Manifest.from_dict(data)


@dataclass(frozen=True)
class RuntimeSpec:
    """Runtime configuration."""
    provider: str
    version: str
    source: str | None = None
    channel: str | None = None
    digest: str | None = None
    runner: str | None = None
    image: str | None = None
    network: str = "none"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeSpec:
        _reject_unknown(data, RUNTIME_FIELDS, "runtime")
        provider = _required_str(data, "runtime.provider")
        version = _required_str(data, "runtime.version")
        network = _optional_str(data, "network") or "none"
        
        if network not in ALLOWED_RUNTIME_NETWORK_MODES:
            raise ManifestError(
                f"runtime.network must be one of {sorted(ALLOWED_RUNTIME_NETWORK_MODES)}, got {network!r}"
            )

        from runtime.catalog import list_catalog_providers, resolve_catalog_version

        if resolve_catalog_version(provider, version, _optional_str(data, "channel")) is None:
            known = set(list_catalog_providers())
            if provider not in known:
                raise ManifestError(f"unsupported runtime provider: {provider}")
            raise ManifestError(
                f"unsupported runtime version for {provider}: {version}. "
                "Add it to runtime/catalog.json before building."
            )
        
        return cls(
            provider=provider,
            version=version,
            source=_optional_str(data, "source"),
            channel=_optional_str(data, "channel"),
            digest=_optional_str(data, "digest"),
            runner=_optional_str(data, "runner"),
            image=_optional_str(data, "image") or _optional_str(data, "imageRef"),
            network=network,
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none({
            "provider": self.provider,
            "version": self.version,
            "source": self.source,
            "channel": self.channel,
            "digest": self.digest,
            "runner": self.runner,
            "image": self.image,
            "network": self.network,
        })


@dataclass(frozen=True)
class BuildSpec:
    """Build-time settings kept separate from runtime settings."""
    network: str = "none"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BuildSpec:
        data = data or {}
        if not isinstance(data, dict):
            raise ManifestError("build must be a dict")
        _reject_unknown(data, BUILD_FIELDS, "build")
        network = _optional_str(data, "network") or "none"
        if network not in ALLOWED_RUNTIME_NETWORK_MODES:
            raise ManifestError(
                f"build.network must be one of {sorted(ALLOWED_RUNTIME_NETWORK_MODES)}, got {network!r}"
            )
        return cls(network=network)

    def to_dict(self) -> dict[str, Any]:
        return {"network": self.network}


@dataclass(frozen=True)
class LaunchSpec:
    """Launch configuration."""
    entrypoint: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    working_directory: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LaunchSpec:
        _reject_unknown(data, LAUNCH_FIELDS, "launch")
        args = data.get("args", []) or []
        env = data.get("env", {}) or {}
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise ManifestError("launch.args must be a list of strings")
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ManifestError("launch.env must be an object with string keys and values")
        return cls(
            entrypoint=_required_str(data, "launch.entrypoint"),
            args=args,
            env=env,
            working_directory=_optional_str(data, "workingDirectory"),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none({
            "entrypoint": self.entrypoint,
            "args": self.args,
            "env": self.env,
            "workingDirectory": self.working_directory,
        })


@dataclass(frozen=True)
class SourceSpec:
    """Source declaration for integrity verification."""
    id: str
    type: str
    policy: str
    url: str | None = None
    source: str | None = None
    path: str | None = None
    sha256: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> SourceSpec:
        if not isinstance(data, dict):
            raise ManifestError(f"sources[{index}] must be an object")
        _reject_unknown(data, SOURCE_FIELDS, f"sources[{index}]")
        sid = _optional_str(data, "id") or _optional_str(data, "name")
        if not sid:
            raise ManifestError(f"sources[{index}].id or sources[{index}].name is required")
        source_type = _required_str(data, f"sources[{index}].type")
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise ManifestError(
                f"sources[{index}].type must be one of: " + ", ".join(sorted(ALLOWED_SOURCE_TYPES))
            )
        policy = _required_str(data, f"sources[{index}].policy")
        if policy not in ALLOWED_SOURCE_POLICIES:
            raise ManifestError(
                f"sources[{index}].policy must be one of: " + ", ".join(sorted(ALLOWED_SOURCE_POLICIES))
            )
        return cls(
            id=sid,
            type=source_type,
            policy=policy,
            url=_optional_str(data, "url"),
            source=_optional_str(data, "source"),
            path=_optional_str(data, "path"),
            sha256=_optional_str(data, "sha256"),
            description=_optional_str(data, "description"),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none({
            "id": self.id,
            "type": self.type,
            "policy": self.policy,
            "url": self.url,
            "source": self.source,
            "path": self.path,
            "sha256": self.sha256,
            "description": self.description,
        })


def resolve_module_capabilities(modules: list[ModuleBase]) -> dict[str, dict[str, Any]]:
    """Resolve declared module capability providers or raise on conflicts."""
    resolved: dict[str, dict[str, Any]] = {}
    for index, module in enumerate(modules):
        for slot, provider in module.capabilities().items():
            claim = {
                "slot": slot,
                "provider": provider,
                "moduleType": module.type,
                "moduleIndex": index,
            }
            existing = resolved.get(slot)
            if existing and existing["provider"] != provider:
                raise ManifestError(
                    "modules cannot be used together; PowerShell capability conflict on "
                    f"slot '{slot}': {existing['moduleType']} provides "
                    f"{existing['provider']}, but {module.type} provides {provider}"
                )
            resolved[slot] = claim
    return resolved


def _validate_module_combinations(modules: list[ModuleBase]) -> None:
    """Validate module capability combinations."""
    resolve_module_capabilities(modules)


def _validate_cfw_boundary(
    runtime: RuntimeSpec,
    modules: list[ModuleBase],
    launch: LaunchSpec | None,
    compatibility: dict[str, Any],
) -> None:
    """Keep CFW prepared prefixes opaque to Cage compatibility machinery."""
    chocolatey_modules = [module for module in modules if module.type == "chocolatey"]
    if not chocolatey_modules:
        return
    if runtime.provider != "wine" or runtime.version != "11.0":
        raise ManifestError("Chocolatey Phase 1 CFW prepared runtimes require Wine 11.0")
    identities: set[tuple[str, str, str]] = set()
    for module in chocolatey_modules:
        resolver = getattr(module, "_runtime_artifact", None)
        artifact = resolver() if callable(resolver) else None
        if isinstance(artifact, dict):
            identities.add((artifact["id"], artifact["manifestSha256"], artifact["wineImage"]))
    if len(identities) > 1:
        raise ManifestError("Chocolatey modules declare conflicting CFW prepared runtimes")
    if len(chocolatey_modules) > 1:
        raise ManifestError("CFW prepared runtimes require exactly one Chocolatey module")
    producer_environment: dict[str, str] = {}
    resolver = getattr(chocolatey_modules[0], "_runtime_artifact", None)
    artifact = resolver() if callable(resolver) else None
    if isinstance(artifact, dict):
        producer_environment = dict(artifact.get("environment") or {})
    launch_collisions = sorted(set(launch.env if launch else {}) & set(producer_environment))
    if launch_collisions:
        raise ManifestError(
            "CFW launch.env cannot override producer-owned environment: "
            + ", ".join(launch_collisions)
        )
    if runtime.runner is not None:
        raise ManifestError(
            "CFW prepared runtimes cannot use runtime.runner; the producer image owns Wine identity"
        )
    if compatibility:
        raise ManifestError("CFW prepared runtimes cannot declare Cage compatibility policy")
    mutating = sorted({
        module.type for module in modules
        if module.type in {"winetricks", "script", "containerfile"}
    })
    if mutating:
        raise ManifestError(
            "CFW prepared runtimes cannot combine with compatibility-mutating module: "
            + ", ".join(mutating)
        )


@dataclass(frozen=True)
class Manifest:
    """Simplified Manifest for module-first architecture.
    
    This Manifest parses modules directly without expansion into intermediate fields.
    Modules are first-class build directives that generate build steps.
    """
    schema_version: str
    name: str
    version: str
    runtime: RuntimeSpec
    build: BuildSpec = field(default_factory=BuildSpec)
    modules: list[ModuleBase] = field(default_factory=list)
    sources: list[SourceSpec] = field(default_factory=list)
    launch: LaunchSpec | None = None
    compatibility: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    exports: list[dict[str, Any]] = field(default_factory=list)
    entrypoints: list[dict[str, Any]] = field(default_factory=list)
    file_associations: list[dict[str, Any]] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        """Parse a manifest from a dict.
        
        This is the new simplified parser that handles modules directly.
        """
        if not isinstance(data, dict):
            raise ManifestError("manifest must be an object")
        _reject_unknown(data, ROOT_FIELDS, "manifest")
        
        schema_version = _required_str(data, "schemaVersion")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ManifestError(
                "schemaVersion must be one of: " + ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
            )
        name = _required_str(data, "name")
        version = _required_str(data, "version")
        
        # Parse runtime
        runtime_data = data.get("runtime", {})
        if not isinstance(runtime_data, dict):
            raise ManifestError("runtime must be a dict")
        runtime = RuntimeSpec.from_dict(runtime_data)
        build = BuildSpec.from_dict(data.get("build"))
        
        # Parse modules (first-class, no expansion)
        modules_data = data.get("modules", []) or []
        if not isinstance(modules_data, list):
            raise ManifestError("modules must be a list")
        try:
            modules = [parse_module(m, i) for i, m in enumerate(modules_data)]
        except ModuleError as exc:
            raise ManifestError(str(exc)) from exc
        _validate_module_combinations(modules)
        
        # Parse sources
        sources_data = data.get("sources", []) or []
        if not isinstance(sources_data, list):
            raise ManifestError("sources must be a list")
        sources = [SourceSpec.from_dict(s, i) for i, s in enumerate(sources_data)]
        source_ids = [source.id for source in sources]
        duplicate_source_ids = sorted({sid for sid in source_ids if source_ids.count(sid) > 1})
        if duplicate_source_ids:
            raise ManifestError("duplicate source id(s): " + ", ".join(duplicate_source_ids))
        
        # Parse launch
        launch_data = data.get("launch")
        if launch_data is not None and not isinstance(launch_data, dict):
            raise ManifestError("launch must be a dict")
        launch = LaunchSpec.from_dict(launch_data) if launch_data is not None else None
        
        # Parse config before compatibility so legacy config can normalize into
        # the explicit first-class compatibility policy.
        config = data.get("config", {}) or {}
        if not isinstance(config, dict):
            raise ManifestError("config must be a dict")

        raw_compatibility = data.get("compatibility", {}) or {}
        if not isinstance(raw_compatibility, dict):
            raise ManifestError("compatibility must be a dict")
        try:
            compatibility = normalize_compatibility_policy(
                config=config,
                compatibility=raw_compatibility,
            )
        except CompatibilityPolicyError as exc:
            raise ManifestError(str(exc)) from exc
        _validate_cfw_boundary(runtime, modules, launch, compatibility)
        
        # Parse provenance
        provenance = data.get("provenance", {}) or {}
        if not isinstance(provenance, dict):
            raise ManifestError("provenance must be a dict")
        
        # Parse exports
        exports = data.get("exports", []) or []
        if not isinstance(exports, list):
            raise ManifestError("exports must be a list")
        
        # Parse entrypoints
        entrypoints = data.get("entrypoints", []) or []
        if not isinstance(entrypoints, list) or not all(isinstance(x, dict) for x in entrypoints):
            raise ManifestError("entrypoints must be a list of objects")
        
        # Parse file associations
        file_associations = data.get("fileAssociations", []) or []
        if not isinstance(file_associations, list) or not all(isinstance(x, dict) for x in file_associations):
            raise ManifestError("fileAssociations must be a list of objects")
        
        # Parse profiles
        profiles = data.get("profiles", []) or []
        if not isinstance(profiles, list) or not all(isinstance(x, str) and x for x in profiles):
            raise ManifestError("profiles must be a list of non-empty strings")
        
        return cls(
            schema_version=schema_version,
            name=name,
            version=version,
            runtime=runtime,
            build=build,
            modules=modules,
            sources=sources,
            launch=launch,
            compatibility=compatibility,
            config=config,
            provenance=provenance,
            exports=exports,
            entrypoints=entrypoints,
            file_associations=file_associations,
            profiles=profiles,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert manifest to dict."""
        result = {
            "schemaVersion": self.schema_version,
            "name": self.name,
            "version": self.version,
            "runtime": self.runtime.to_dict(),
        }
        if self.build.network != "none":
            result["build"] = self.build.to_dict()
        
        if self.modules:
            result["modules"] = [m.to_dict() for m in self.modules]
        
        if self.sources:
            result["sources"] = [s.to_dict() for s in self.sources]
        
        if self.launch:
            result["launch"] = self.launch.to_dict()
        
        if self.compatibility:
            result["compatibility"] = self.compatibility
        
        if self.config:
            result["config"] = self.config
        
        if self.provenance:
            result["provenance"] = self.provenance
        
        if self.exports:
            result["exports"] = self.exports
        
        if self.entrypoints:
            result["entrypoints"] = self.entrypoints
        
        if self.file_associations:
            result["fileAssociations"] = self.file_associations
        
        if self.profiles:
            result["profiles"] = self.profiles
        
        return result


__all__ = ["Manifest", "RuntimeSpec", "BuildSpec", "LaunchSpec", "SourceSpec", "resolve_module_capabilities"]
