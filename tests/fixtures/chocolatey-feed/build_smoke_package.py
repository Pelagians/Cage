"""Build the deterministic Cage Chocolatey smoke nupkg."""
from __future__ import annotations

from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent / "source"
OUTPUTS = (
    Path(__file__).resolve().parent / "cage-chocolatey-smoke.0.1.0.nupkg",
    ROOT / "core/chocolatey/assets/cage-chocolatey-smoke.0.1.0.nupkg",
)
MEMBERS = (
    (SOURCE / "cage-chocolatey-smoke.nuspec", "cage-chocolatey-smoke.nuspec"),
    (SOURCE / "tools/chocolateyInstall.ps1", "tools/chocolateyInstall.ps1"),
    (SOURCE / "tools/chocolateyUninstall.ps1", "tools/chocolateyUninstall.ps1"),
)


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, name in MEMBERS:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


if __name__ == "__main__":
    for destination in OUTPUTS:
        build(destination)
        print(destination)
