"""Pluggable runtime provider abstraction with runtime catalog binding."""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Any, Protocol

from core.manifest import ManifestError, RuntimeSpec
from runtime.catalog import (
    list_catalog_providers,
    resolve_catalog_version,
)
from runtime.runner_catalog import RunnerCatalogError, resolve_runner_spec


@dataclass(frozen=True)
class RuntimeBinding:
    provider: str
    version: str
    launcher: str
    requested_version: str | None = None
    resolved_version: str | None = None
    family: str | None = None
    runner: str | None = None
    runner_version: str | None = None
    runner_source: str | None = None
    runner_url: str | None = None
    runner_sha256: str | None = None
    runner_arch: str | None = None
    package_version: str | None = None
    launcher_version: str | None = None
    source: str | None = None
    channel: str | None = None
    digest: str | None = None
    notes: str | None = None
    oci_image: str | None = None
    local_oci_image: str | None = None
    runtime_usable: bool | None = None
    environment: dict[str, str] | None = None

    def to_dict(self):
        d = {k: v for k, v in {
            "provider": self.provider,
            "version": self.version,
            "requestedVersion": self.requested_version,
            "resolvedVersion": self.resolved_version,
            "family": self.family,
            "runner": self.runner,
            "runnerVersion": self.runner_version,
            "runnerSource": self.runner_source,
            "runnerUrl": self.runner_url,
            "runnerSha256": self.runner_sha256,
            "runnerArch": self.runner_arch,
            "packageVersion": self.package_version,
            "launcher": self.launcher,
            "launcherVersion": self.launcher_version,
            "source": self.source,
            "channel": self.channel,
            "digest": self.digest,
            "notes": self.notes,
            "ociImage": self.oci_image,
            "localOciImage": self.local_oci_image,
            "runtimeUsable": self.runtime_usable,
            "environment": self.environment,
        }.items() if v is not None}
        return d


class RuntimeProvider(Protocol):
    name: str
    def resolve(self, spec: RuntimeSpec) -> RuntimeBinding: ...


_EXTRA_PROVIDERS: dict[str, RuntimeProvider] = {}

def resolve_oci_image(provider: str, version: str,
                      channel: str | None = None,
                      *, published: bool = True) -> str | None:
    """Resolve provider/version to an OCI image ref from the catalog.

    By default this returns the published GHCR ref, because that is what a
    normal Forge build should pull after CI publishes the runtime catalog.
    Pass ``published=False`` for the local developer tag.
    """
    entry = resolve_catalog_version(provider, version, channel)
    if entry is None:
        return None
    return entry.published_ref if published else entry.local_ref

def resolve_local_oci_image(provider: str, version: str,
                            channel: str | None = None) -> str | None:
    return resolve_oci_image(provider, version, channel, published=False)

def register_provider(provider: RuntimeProvider):
    _EXTRA_PROVIDERS[provider.name] = provider

def resolve_runtime(spec: RuntimeSpec) -> RuntimeBinding:
    if spec.provider in _EXTRA_PROVIDERS:
        return _EXTRA_PROVIDERS[spec.provider].resolve(spec)

    entry = resolve_catalog_version(spec.provider, spec.version, spec.channel)
    if entry is None:
        known = set(list_catalog_providers())
        if spec.provider not in known:
            raise ManifestError(f"unsupported runtime provider: {spec.provider}")
        raise ManifestError(
            f"unsupported runtime version for {spec.provider}: {spec.version}. "
            "Add it to runtime/catalog.json before building."
        )

    runner = entry.runner
    runner_version = entry.runner_version
    runner_source = None
    runner_url = None
    runner_sha256 = None
    runner_arch = None
    if spec.runner:
        try:
            runner_spec = resolve_runner_spec(spec.runner)
        except RunnerCatalogError as exc:
            raise ManifestError(str(exc)) from exc
        if runner_spec.provider != spec.provider:
            raise ManifestError(
                f"runtime.runner {spec.runner!r} is for provider {runner_spec.provider}, "
                f"not {spec.provider}"
            )
        runner = runner_spec.id
        runner_version = runner_spec.version
        runner_source = runner_spec.source
        runner_url = runner_spec.url
        runner_sha256 = runner_spec.sha256
        runner_arch = runner_spec.arch

    return RuntimeBinding(
        provider=spec.provider,
        version=entry.version,
        requested_version=entry.requested_version,
        resolved_version=entry.resolved_version,
        family=entry.family,
        runner=runner,
        runner_version=runner_version,
        runner_source=runner_source,
        runner_url=runner_url,
        runner_sha256=runner_sha256,
        runner_arch=runner_arch,
        package_version=entry.package_version,
        launcher=entry.launcher,
        launcher_version=entry.launcher_version,
        source=spec.source,
        channel=entry.channel or spec.channel,
        digest=spec.digest,
        notes=entry.notes,
        oci_image=spec.image or entry.published_ref,
        local_oci_image=entry.local_ref,
        runtime_usable=entry.runtime_usable,
    )


def required_cfw_runtime_artifact(manifest) -> dict[str, Any] | None:
    """Return one fully resolved, coherent CFW trust-root artifact."""
    artifacts: list[dict[str, Any]] = []
    identities: set[tuple[object, ...]] = set()
    for module in manifest.modules:
        if getattr(module, "type", None) != "chocolatey":
            continue
        resolver = getattr(module, "_runtime_artifact", None)
        artifact = resolver() if callable(resolver) else None
        if isinstance(artifact, dict):
            normalized = dict(artifact)
            artifacts.append(normalized)
            identities.add((
                normalized["id"],
                normalized["manifestSha256"],
                normalized["wineImage"],
                tuple(normalized["wineVersions"]),
                tuple(sorted(normalized["environment"].items())),
            ))
    if len(identities) > 1:
        raise ManifestError("Chocolatey modules declare conflicting CFW prepared runtimes")
    return artifacts[0] if artifacts else None


def required_cfw_runtime_image(manifest) -> str | None:
    """Return the producer image from one coherent CFW trust-root artifact."""
    artifact = required_cfw_runtime_artifact(manifest)
    return artifact["wineImage"] if artifact is not None else None


def resolve_manifest_runtime(manifest) -> RuntimeBinding:
    """Resolve a manifest runtime, honoring a CFW producer-image lock."""
    binding = resolve_runtime(manifest.runtime)
    artifact = required_cfw_runtime_artifact(manifest)
    if artifact is None:
        return binding
    image = artifact["wineImage"]
    return replace(
        binding,
        oci_image=image,
        local_oci_image=None,
        digest=image.rsplit("@sha256:", 1)[1],
        environment=dict(artifact["environment"]),
    )


def list_providers() -> list[str]:
    return sorted(set(list_catalog_providers()) | set(_EXTRA_PROVIDERS))


def resolve_image(provider: str, version: str) -> str | None:
    return resolve_oci_image(provider, version)
