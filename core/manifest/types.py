"""Manifest type definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import (
    RUNTIME_FIELDS, LAUNCH_FIELDS,
    DEPENDENCY_FIELDS, INSTALL_FIELDS, FILESYSTEM_FIELDS,
    SOURCE_FIELDS, ENTRYPOINT_FIELDS, FILE_ASSOCIATION_FIELDS,
    ALLOWED_RUNTIME_PROVIDERS, ALLOWED_RUNTIME_NETWORK_MODES,
    ALLOWED_DEPENDENCY_KINDS, ALLOWED_INSTALL_KINDS,
    ALLOWED_SOURCE_TYPES, ALLOWED_SOURCE_POLICIES,
    ALLOWED_FILE_MAPPING_MODES, CHOCO_ARG_RE,
)
from .errors import ManifestError
from .helpers import _reject_unknown, _required_str, _optional_str, _drop_none

@dataclass(frozen=True)
class RuntimeSpec:
    provider: str
    version: str
    source: str | None = None
    channel: str | None = None
    digest: str | None = None
    runner: str | None = None
    network: str = "none"

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        _reject_unknown(data, RUNTIME_FIELDS, "runtime")
        provider = _required_str(data, "runtime.provider")
        version = _required_str(data, "runtime.version")
        if provider not in ALLOWED_RUNTIME_PROVIDERS:
            raise ManifestError("runtime.provider must be one of: " + ", ".join(sorted(ALLOWED_RUNTIME_PROVIDERS)))
        network = _optional_str(data, "network") or "none"
        if network not in ALLOWED_RUNTIME_NETWORK_MODES:
            raise ManifestError("runtime.network must be one of: " + ", ".join(sorted(ALLOWED_RUNTIME_NETWORK_MODES)))
        return cls(
            provider,
            version,
            _optional_str(data, "source"),
            _optional_str(data, "channel"),
            _optional_str(data, "digest"),
            _optional_str(data, "runner"),
            network,
        )

    def to_dict(self):
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
class DependencySpec:
    kind: str
    verbs: list[str] = field(default_factory=list)
    name: str | None = None
    version: str | None = None
    sha256: str | None = None

    @classmethod
    def from_dict(cls, data, index):
        _reject_unknown(data, DEPENDENCY_FIELDS, f"dependencies[{index}]")
        kind = _required_str(data, f"dependencies[{index}].kind")
        if kind not in ALLOWED_DEPENDENCY_KINDS:
            raise ManifestError(
                f"dependencies[{index}].kind must be one of: " + ", ".join(sorted(ALLOWED_DEPENDENCY_KINDS))
            )
        verbs = data.get("verbs", []) or []
        if not isinstance(verbs, list) or not all(isinstance(x, str) and x for x in verbs):
            raise ManifestError(f"dependencies[{index}].verbs must be a list of non-empty strings")
        return cls(kind, verbs, _optional_str(data, "name"), _optional_str(data, "version"), _optional_str(data, "sha256"))

    def to_dict(self):
        return _drop_none({
            "kind": self.kind,
            "verbs": self.verbs,
            "name": self.name,
            "version": self.version,
            "sha256": self.sha256,
        })


@dataclass(frozen=True)
class InstallStep:
    kind: str
    source: str | None = None
    sha256: str | None = None
    target: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    working_directory: str | None = None

    @classmethod
    def from_dict(cls, data, index):
        _reject_unknown(data, INSTALL_FIELDS, f"install[{index}]")
        kind = _required_str(data, f"install[{index}].kind")
        if kind not in ALLOWED_INSTALL_KINDS:
            raise ManifestError(f"install[{index}].kind must be one of: " + ", ".join(sorted(ALLOWED_INSTALL_KINDS)))
        args = data.get("args", []) or []
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise ManifestError(f"install[{index}].args must be a list of strings")
        if kind in {"msi", "exe", "portable", "bat", "cmd"} and not data.get("source"):
            raise ManifestError(f"install[{index}].source is required for {kind}")
        if kind == "script" and not data.get("command"):
            raise ManifestError(f"install[{index}].command is required for script")
        if kind == "choco":
            command = _optional_str(data, "command")
            if command != "install":
                raise ManifestError(f"install[{index}].command must be install for choco")
            if not args:
                raise ManifestError(f"install[{index}].args must include a Chocolatey package")
            for arg_index, arg in enumerate(args):
                if not CHOCO_ARG_RE.fullmatch(arg):
                    raise ManifestError(
                        f"install[{index}].args[{arg_index}] must use letters, numbers, dot, underscore, plus, or dash"
                    )
        return cls(
            kind,
            _optional_str(data, "source"),
            _optional_str(data, "sha256"),
            _optional_str(data, "target"),
            _optional_str(data, "command"),
            args,
            _optional_str(data, "workingDirectory"),
        )

    def to_dict(self):
        return _drop_none({
            "kind": self.kind,
            "source": self.source,
            "sha256": self.sha256,
            "target": self.target,
            "command": self.command,
            "args": self.args,
            "workingDirectory": self.working_directory,
        })


@dataclass(frozen=True)
class FileMapping:
    source: str
    target: str
    sha256: str | None = None
    mode: str = "copy"

    @classmethod
    def from_dict(cls, data, index):
        _reject_unknown(data, FILESYSTEM_FIELDS, f"filesystem[{index}]")
        mode = _optional_str(data, "mode") or "copy"
        if mode not in ALLOWED_FILE_MAPPING_MODES:
            raise ManifestError(f"filesystem[{index}].mode must be one of: " + ", ".join(sorted(ALLOWED_FILE_MAPPING_MODES)))
        return cls(
            _required_str(data, f"filesystem[{index}].source"),
            _required_str(data, f"filesystem[{index}].target"),
            _optional_str(data, "sha256"),
            mode,
        )

    def to_dict(self):
        return _drop_none({"source": self.source, "target": self.target, "sha256": self.sha256, "mode": self.mode})


@dataclass(frozen=True)
class SourceDeclaration:
    id: str
    type: str
    policy: str
    url: str | None = None
    source: str | None = None
    path: str | None = None
    sha256: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, data, index):
        _reject_unknown(data, SOURCE_FIELDS, f"sources[{index}]")
        sid = _optional_str(data, "id") or _optional_str(data, "name")
        if not sid:
            raise ManifestError(f"sources[{index}].id is required")
        source_type = _optional_str(data, "type") or "other"
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise ManifestError(f"sources[{index}].type must be one of: " + ", ".join(sorted(ALLOWED_SOURCE_TYPES)))
        policy = _optional_str(data, "policy") or "external-local-file-required"
        if policy not in ALLOWED_SOURCE_POLICIES:
            raise ManifestError(f"sources[{index}].policy must be one of: " + ", ".join(sorted(ALLOWED_SOURCE_POLICIES)))
        return cls(
            sid,
            source_type,
            policy,
            _optional_str(data, "url"),
            _optional_str(data, "source"),
            _optional_str(data, "path"),
            _optional_str(data, "sha256"),
            _optional_str(data, "description"),
        )

    @property
    def ref(self) -> str | None:
        return self.url or self.source or self.path

    def to_dict(self):
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

    def __getitem__(self, key: str) -> Any:
        # Backward-compatible read path for older code/tests that treated
        # manifest.sources entries as raw dictionaries. `name` aliases the new
        # normalized source id.
        data = self.to_dict()
        if key == "name":
            return self.id
        return data[key]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


@dataclass(frozen=True)
class SuiteEntrypoint:
    id: str
    name: str
    executable: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    working_directory: str | None = None

    @classmethod
    def from_dict(cls, data, index):
        _reject_unknown(data, ENTRYPOINT_FIELDS, f"entrypoints[{index}]")
        args = data.get("args", []) or []
        env = data.get("env", {}) or {}
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise ManifestError(f"entrypoints[{index}].args must be a list of strings")
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ManifestError(f"entrypoints[{index}].env must be an object with string keys and values")
        return cls(
            _required_str(data, f"entrypoints[{index}].id"),
            _required_str(data, f"entrypoints[{index}].name"),
            _required_str(data, f"entrypoints[{index}].executable"),
            args,
            env,
            _optional_str(data, "workingDirectory"),
        )

    def to_dict(self):
        return _drop_none({
            "id": self.id,
            "name": self.name,
            "executable": self.executable,
            "args": self.args,
            "env": self.env,
            "workingDirectory": self.working_directory,
        })


@dataclass(frozen=True)
class FileAssociation:
    entrypoint: str
    extensions: list[str] = field(default_factory=list)
    mime: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data, index):
        _reject_unknown(data, FILE_ASSOCIATION_FIELDS, f"fileAssociations[{index}]")
        extensions = data.get("extensions", []) or []
        mime = data.get("mime", []) or []
        if not isinstance(extensions, list) or not all(isinstance(x, str) and x.startswith(".") for x in extensions):
            raise ManifestError(f"fileAssociations[{index}].extensions must be a list of extensions like .docx")
        if not isinstance(mime, list) or not all(isinstance(x, str) and x for x in mime):
            raise ManifestError(f"fileAssociations[{index}].mime must be a list of MIME strings")
        return cls(_required_str(data, f"fileAssociations[{index}].entrypoint"), extensions, mime)

    def to_dict(self):
        return _drop_none({"entrypoint": self.entrypoint, "extensions": self.extensions, "mime": self.mime})


@dataclass(frozen=True)
class LaunchSpec:
    entrypoint: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    working_directory: str | None = None

    @classmethod
    def from_dict(cls, data):
        _reject_unknown(data, LAUNCH_FIELDS, "launch")
        args = data.get("args", []) or []
        env = data.get("env", {}) or {}
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise ManifestError("launch.args must be a list of strings")
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ManifestError("launch.env must be an object with string keys and values")
        return cls(_required_str(data, "launch.entrypoint"), args, env, _optional_str(data, "workingDirectory"))

    def to_dict(self):
        return _drop_none({
            "entrypoint": self.entrypoint,
            "args": self.args,
            "env": self.env,
            "workingDirectory": self.working_directory,
        })


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
