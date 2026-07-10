"""Load and render packaged Chocolatey shell assets."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import re
from typing import Mapping


class ChocolateyAssetError(ValueError):
    """Raised when a packaged Chocolatey asset cannot be safely rendered."""


_TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def load_asset_bytes(name: str) -> bytes:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ChocolateyAssetError(f"invalid Chocolatey asset name: {name}")
    resource = files(__package__).joinpath(name)
    if not resource.is_file():
        raise ChocolateyAssetError(f"unknown Chocolatey asset: {name}")
    return resource.read_bytes()


def load_asset(name: str) -> str:
    try:
        return load_asset_bytes(name).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChocolateyAssetError(f"Chocolatey asset is not UTF-8 text: {name}") from exc


def asset_sha256(name: str) -> str:
    return hashlib.sha256(load_asset_bytes(name)).hexdigest()


def render_asset(name: str, values: Mapping[str, str]) -> str:
    template = load_asset(name)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ChocolateyAssetError(
                f"Chocolatey asset {name} requires template value {key}"
            )
        return str(values[key])

    rendered = _TOKEN_RE.sub(replace, template)
    remaining = _TOKEN_RE.findall(rendered)
    if remaining:
        raise ChocolateyAssetError(
            f"Chocolatey asset {name} has unresolved template values: {remaining}"
        )
    return rendered.rstrip()
