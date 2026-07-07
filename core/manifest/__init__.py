"""Manifest package - recipe schema and validation for Cage v0."""
from __future__ import annotations

from .errors import ManifestError
from .constants import (
    SCHEMA_VERSION, LEGACY_SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS,
    ALLOWED_RUNTIME_PROVIDERS, ALLOWED_RUNTIME_NETWORK_MODES,
    ALLOWED_DEPENDENCY_KINDS, ALLOWED_INSTALL_KINDS,
    ALLOWED_SOURCE_TYPES, ALLOWED_SOURCE_POLICIES,
    ALLOWED_FILE_MAPPING_MODES,
    ROOT_FIELDS, RUNTIME_FIELDS, DEPENDENCY_FIELDS, INSTALL_FIELDS,
    FILESYSTEM_FIELDS, LAUNCH_FIELDS, SOURCE_FIELDS, ENTRYPOINT_FIELDS,
    FILE_ASSOCIATION_FIELDS,
)
from .types import (
    RuntimeSpec, DependencySpec, InstallStep, FileMapping,
    SourceDeclaration, SuiteEntrypoint, FileAssociation,
    LaunchSpec,
)
from .manifest import Manifest, load_manifest

__all__ = [
    "Manifest",
    "load_manifest",
    "ManifestError",
    "RuntimeSpec",
    "DependencySpec",
    "InstallStep",
    "FileMapping",
    "SourceDeclaration",
    "SuiteEntrypoint",
    "FileAssociation",
    "LaunchSpec",
    "SCHEMA_VERSION",
    "LEGACY_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
]
