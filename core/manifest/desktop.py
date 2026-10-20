"""Optional desktop identity shared by application export formats."""
from __future__ import annotations

import re
from .errors import ManifestError


def normalize_desktop(value):
    if value is None:
        return {}
    allowed = {"id", "name", "summary", "license", "homepage", "categories", "documentsDirectory"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ManifestError("desktop must be an object containing only " + ", ".join(sorted(allowed)))
    result = dict(value)
    for key in ("id", "name", "summary", "license", "homepage", "documentsDirectory"):
        item = result.get(key)
        if not isinstance(item, str) or not item or any(ord(c) < 32 for c in item):
            raise ManifestError(f"desktop.{key} must be a nonempty single-line string")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){2,}", result["id"]):
        raise ManifestError("desktop.id must be a reverse-DNS application ID")
    if not re.fullmatch(r"[A-Za-z0-9 _-]+", result["documentsDirectory"]):
        raise ManifestError("desktop.documentsDirectory must be one safe Documents subdirectory")
    if not result["homepage"].startswith("https://"):
        raise ManifestError("desktop.homepage must be an HTTPS URL")
    categories = result.get("categories", ["Utility"])
    if not isinstance(categories, list) or not categories or not all(
        isinstance(c, str) and re.fullmatch(r"[A-Za-z]+", c) for c in categories
    ):
        raise ManifestError("desktop.categories must be a list of desktop category names")
    result["categories"] = categories
    return result
