"""Simplified Manifest for module-first architecture.

This is the new Manifest that parses modules directly without expansion.
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .errors import ManifestError
from .helpers import _reject_unknown, _required_str, _optional_str, _drop_none
from .constants import ROOT_FIELDS, RUNTIME_FIELDS, LAUNCH_FIELDS, SOURCE_FIELDS
from ..modules import parse_module, ModuleBase


def _load_strict_yaml(text: str) -> dict[str, Any]:
    """Load YAML with strict parsing."""
    try:
        import yaml
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ManifestError("YAML root must be a dict")
        return data
    except ImportError:
        raise ManifestError("PyYAML is required for YAML support")
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML: {exc}") from exc


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
    network: str = "none"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeSpec:
        _reject_unknown(data, RUNTIME_FIELDS, "runtime")
        provider = _required_str(data, "runtime.provider")
        version = _required_str(data, "runtime.version")
        network = _optional_str(data, "network") or "none"
        
        # Validate network mode
        valid_network_modes = {"none", "bridge", "host"}
        if network not in valid_network_modes:
            raise ManifestError(
                f"runtime.network must be one of {sorted(valid_network_modes)}, got {network!r}"
            )
        
        return cls(
            provider=provider,
            version=version,
            source=_optional_str(data, "source"),
            channel=_optional_str(data, "channel"),
            digest=_optional_str(data, "digest"),
            runner=_optional_str(data, "runner"),
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
            "network": self.network,
        })


@dataclass(frozen=True)
class LaunchSpec:
    """Launch configuration."""
    entrypoint: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LaunchSpec:
        _reject_unknown(data, LAUNCH_FIELDS, "launch")
        args = data.get("args", []) or []
        env = data.get("env", {}) or {}
        if not isinstance(args, list):
            raise ManifestError("launch.args must be a list")
        if not isinstance(env, dict):
            raise ManifestError("launch.env must be a dict")
        return cls(
            entrypoint=_optional_str(data, "entrypoint"),
            args=args,
            env=env,
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none({
            "entrypoint": self.entrypoint,
            "args": self.args,
            "env": self.env,
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
        _reject_unknown(data, SOURCE_FIELDS, f"sources[{index}]")
        sid = _optional_str(data, "id") or _optional_str(data, "name")
        if not sid:
            raise ManifestError(f"sources[{index}].id or sources[{index}].name is required")
        return cls(
            id=sid,
            type=_required_str(data, f"sources[{index}].type"),
            policy=_required_str(data, f"sources[{index}].policy"),
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
        _reject_unknown(data, ROOT_FIELDS, "manifest")
        
        schema_version = _required_str(data, "schemaVersion")
        name = _required_str(data, "name")
        version = _required_str(data, "version")
        
        # Parse runtime
        runtime_data = data.get("runtime", {})
        if not isinstance(runtime_data, dict):
            raise ManifestError("runtime must be a dict")
        runtime = RuntimeSpec.from_dict(runtime_data)
        
        # Parse modules (first-class, no expansion)
        modules_data = data.get("modules", []) or []
        if not isinstance(modules_data, list):
            raise ManifestError("modules must be a list")
        modules = [parse_module(m, i) for i, m in enumerate(modules_data)]
        
        # Parse sources
        sources_data = data.get("sources", []) or []
        if not isinstance(sources_data, list):
            raise ManifestError("sources must be a list")
        sources = [SourceSpec.from_dict(s, i) for i, s in enumerate(sources_data)]
        
        # Parse launch
        launch_data = data.get("launch")
        launch = LaunchSpec.from_dict(launch_data) if launch_data else None
        
        # Parse compatibility (runtime policy, not a build step)
        compatibility = data.get("compatibility", {}) or {}
        if not isinstance(compatibility, dict):
            raise ManifestError("compatibility must be a dict")
        
        # Parse config
        config = data.get("config", {}) or {}
        if not isinstance(config, dict):
            raise ManifestError("config must be a dict")
        
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
        if not isinstance(entrypoints, list):
            raise ManifestError("entrypoints must be a list")
        
        # Parse file associations
        file_associations = data.get("fileAssociations", []) or []
        if not isinstance(file_associations, list):
            raise ManifestError("fileAssociations must be a list")
        
        # Parse profiles
        profiles = data.get("profiles", []) or []
        if not isinstance(profiles, list):
            raise ManifestError("profiles must be a list")
        
        return cls(
            schema_version=schema_version,
            name=name,
            version=version,
            runtime=runtime,
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


__all__ = ["Manifest", "RuntimeSpec", "LaunchSpec", "SourceSpec"]
