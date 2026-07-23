"""Test helpers for constructing truthfully runnable Cage bundles."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from artifact.bundle import update_bundle_execution_metadata


def materialize_runnable_prefix(
    bundle: Path,
    *,
    entrypoint: str,
    chocolatey: bool = False,
) -> None:
    """Populate the canonical prefix and mark it runnable for unit tests."""
    prefix = bundle / "prefix"
    shutil.rmtree(prefix, ignore_errors=True)
    (prefix / "drive_c/windows").mkdir(parents=True)
    (prefix / "drive_c/windows/system.reg").write_text("wine-registry\n", encoding="utf-8")

    normalized = entrypoint.replace("\\", "/")
    if len(normalized) < 3 or normalized[1:3] != ":/" or normalized[0].lower() != "c":
        raise ValueError(f"test entrypoint must be an absolute C: path: {entrypoint}")
    executable = prefix / "drive_c" / normalized[3:]
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"MZ-test-executable")

    if chocolatey:
        choco = prefix / "drive_c/ProgramData/chocolatey/choco.exe"
        choco.parent.mkdir(parents=True, exist_ok=True)
        choco.write_bytes(b"MZ-test-chocolatey")
        (bundle / "metadata/cfw-runtime-manifest.json").write_text(
            json.dumps({
                "interfaces": {
                    "chocolatey": {
                        "windowsPath": r"C:\ProgramData\chocolatey\choco.exe",
                        "prefixRelativePath": "drive_c/ProgramData/chocolatey/choco.exe",
                        "queryLauncher": "wine",
                        "packageLauncher": "wineconsole",
                    },
                },
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    files = [path for path in prefix.rglob("*") if path.is_file()]
    metadata = {
        "schemaVersion": "cage.prefix-materialization/v0",
        "completed": True,
        "fileCount": len(files),
        "byteSize": sum(path.stat().st_size for path in files),
    }
    (bundle / "metadata/prefix-materialization.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    update_bundle_execution_metadata(
        bundle,
        state="runnable",
        runnable=True,
        dry_run=False,
        materialized_prefix=True,
        has_default_launch=True,
        exit_code=0,
        log_excerpt="test fixture materialized canonical prefix",
    )
