"""Verified, deterministic Linux application layer over a qualified runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from core.modules.paths import validate_linux_outputs


def declared_outputs(bundle: Path) -> list[str]:
    plan = json.loads((bundle / "build/build-plan.json").read_text(encoding="utf-8"))
    return validate_linux_outputs([str(op["metadata"]["path"])
            for op in plan["phases"] if op.get("kind") == "linux-state"])


def linux_state_identity(bundle: Path, base_image: str) -> str | None:
    """Validate a controlled tar layer and hash it with the pinned base reference."""
    paths = declared_outputs(bundle)
    if not paths:
        return None
    archive = bundle / "linux-state.tar"
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("declared Linux state archive is missing or linked")
    expected = [PurePosixPath(path.lstrip("/")) for path in paths]
    seen: set[str] = set()
    try:
        with tarfile.open(archive, "r:") as opened:
            for member in opened:
                name = PurePosixPath(member.name)
                if (member.name != str(name) or name.is_absolute()
                    or any(part in {"", ".", ".."} for part in name.parts)
                    or not any(name == item or item in name.parents for item in expected)
                    or not (member.isfile() or member.isdir())):
                    raise ValueError(f"unsafe Linux layer member: {member.name}")
                if str(name) in seen:
                    raise ValueError(f"duplicate Linux layer member: {member.name}")
                seen.add(str(name))
    except tarfile.TarError as exc:
        raise ValueError(f"invalid Linux state archive: {exc}") from exc
    if not all(any(name == str(item) or name.startswith(str(item) + "/") for name in seen) for item in expected):
        raise ValueError("Linux state archive is missing a declared output")
    digest = hashlib.sha256(base_image.encode("utf-8") + b"\0")
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "cage-app-runtime:" + digest.hexdigest()[:32]
