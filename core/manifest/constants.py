"""Manifest constants and schema definitions."""
from __future__ import annotations

import re

SCHEMA_VERSION = "cage.app/v0"
LEGACY_SCHEMA_VERSION = "cage.dev/v0"
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION, LEGACY_SCHEMA_VERSION}

ALLOWED_RUNTIME_PROVIDERS = {"wine", "staging", "umu-proton-ge"}
ALLOWED_RUNTIME_NETWORK_MODES = {"none", "bridge", "host"}
ALLOWED_DEPENDENCY_KINDS = {"winetricks", "font", "directx", "package", "runtime-component"}
ALLOWED_INSTALL_KINDS = {"msi", "exe", "portable", "choco", "script", "bat", "cmd"}

ROOT_FIELDS = {
    "schemaVersion",
    "name",
    "version",
    "runtime",
    "build",
    "profiles",
    "modules",
    "sources",
    "config",
    "compatibility",
    "launch",
    "entrypoints",
    "fileAssociations",
    "exports",
    "provenance",
}
RUNTIME_FIELDS = {"provider", "version", "source", "channel", "digest", "runner", "network", "image", "imageRef"}
BUILD_FIELDS = {"network"}
DEPENDENCY_FIELDS = {"kind", "verbs", "name", "version", "sha256"}
INSTALL_FIELDS = {"kind", "source", "sha256", "target", "command", "args", "workingDirectory"}
FILESYSTEM_FIELDS = {"source", "target", "sha256", "mode"}
LAUNCH_FIELDS = {"entrypoint", "args", "env", "workingDirectory"}
SOURCE_FIELDS = {"id", "name", "type", "policy", "url", "source", "path", "sha256", "description"}
ENTRYPOINT_FIELDS = {"id", "name", "executable", "args", "env", "workingDirectory"}
FILE_ASSOCIATION_FIELDS = {"entrypoint", "extensions", "mime"}
ALLOWED_SOURCE_TYPES = {"installer", "iso", "archive", "files", "prefix", "font", "other"}
ALLOWED_SOURCE_POLICIES = {"bring-your-own-files", "bring-your-own-installer", "bring-your-own-licensed-media", "bring-your-own-prefix", "redistributable", "synthetic-fixture", "external-local-file-required", "requires-local-installer-and-overlay", "class-marker-only"}
ALLOWED_FILE_MAPPING_MODES = {"copy", "merge"}
CHOCO_ARG_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_.+-]*|--?[A-Za-z0-9][A-Za-z0-9_.-]*)$")
