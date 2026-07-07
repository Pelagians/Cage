"""Manifest package - simplified module-first architecture for Cage."""
from __future__ import annotations

from .errors import ManifestError
from .constants import (
    SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS,
    ROOT_FIELDS, RUNTIME_FIELDS, LAUNCH_FIELDS, SOURCE_FIELDS,
)
from .manifest import Manifest, RuntimeSpec, LaunchSpec, SourceSpec, load_manifest

__all__ = [
    "Manifest",
    "RuntimeSpec",
    "LaunchSpec",
    "SourceSpec",
    "load_manifest",
    "ManifestError",
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
]
