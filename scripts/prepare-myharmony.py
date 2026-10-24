#!/usr/bin/env python3
"""Stage the pinned application payload from a user-supplied MyHarmony MSI."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.media import extract_archive
from runtime.arm64ec import extract_cpio

MSI_SHA256 = "245c352b579a8f79329ca34a1003a496e7834b62011fdd1912775cb81ec19784"
PAYLOAD_SHA256 = "c6ed41de7cd0f2d5f7a7043604ea44621f8f44c6985de674a883535160ccee16"
CAB_MEMBER = "_B8B28107CCE836D5A28A34E41FA81D74"
ZIP_MEMBER = "_20C80DA7B2D34CEDB271E84D73DA24E8"
LDAP_RPM = "wine-ldap-11.20-ec1.fc44.aarch64.rpm"
LDAP_URL = "https://download.copr.fedorainfracloud.org/results/lacamar/wine-arm64ec/fedora-44-aarch64/Packages/w/" + LDAP_RPM
LDAP_SHA256 = "8b58c84b19ac344d47990fe812f440314d5f9485486a3efc3db4e5588df45246"
LDAP_DLL_SHA256 = "47719c3ae006297fc64b846f3e51da9a78c30b5305fe2eaf5b5c34cf316a056c"
FONT_PACKAGES = {
    "arial32.exe": "85297a4d146e9c87ac6f74822734bdee5f4b2a722d7eaa584b7f2cbf76f478f6",
    "trebuc32.exe": "5a690d9bb8510be1b8b4fe49f1f2319651fe51bbe54775ddddd8ef0bd07fdac9",
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(root):
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("linked application input: " + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("--runtime", choices=("wine", "wine-arm64ec"), default="wine")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--wine-ldap-rpm", type=Path, help="use a local copy instead of downloading the pinned Wine LDAP package")
    parser.add_argument("--font-cache", type=Path, help="use local arial32.exe and trebuc32.exe downloads")
    args = parser.parse_args()
    installer = args.installer.resolve()
    if sha(installer) != MSI_SHA256:
        parser.error("installer differs from the qualified MyHarmony 1.0.308 MSI")
    if not shutil.which("7z"):
        parser.error("7z is required to read the MSI's embedded cabinet")
    if args.runtime == "wine-arm64ec" and not shutil.which("rpm2cpio"):
        parser.error("rpm2cpio is required to read the Wine LDAP package")
    destination = args.workspace.resolve() / "sources/myharmony"
    destination.mkdir(parents=True, exist_ok=True)
    if destination.resolve() != destination:
        parser.error("staging destination must not contain symlinks")
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=destination) as temporary:
        temporary = Path(temporary)
        cabinet, payload = temporary / "embedded.cab", temporary / "payload.zip"
        for archive, member, output in [(installer, CAB_MEMBER, cabinet), (cabinet, ZIP_MEMBER, payload)]:
            with output.open("xb") as stream:
                subprocess.run(["7z", "e", "-so", str(archive), member], stdout=stream,
                               stderr=subprocess.PIPE, check=True, timeout=120)
        if sha(payload) != PAYLOAD_SHA256:
            parser.error("embedded application archive differs from the pinned payload")
        extracted = temporary / "app"
        extract_archive(payload, extracted, max_bytes=100 * 1024**2, expected_format="zip")
        app = destination / "app"
        if app.exists():
            if app.is_symlink() or files(app) != files(extracted):
                parser.error("existing staged application differs; preserved without modification")
        else:
            extracted.rename(app)
        for source, target in [(installer, destination / "MyHarmony-App.msi"),
                               (payload, destination / "MyHarmony-payload.zip")]:
            if target.exists():
                if target.is_symlink() or sha(target) != sha(source):
                    parser.error("existing staged input differs: " + str(target))
            else:
                shutil.copyfile(source, target)
        if args.runtime == "wine-arm64ec":
            rpm = args.wine_ldap_rpm or destination / LDAP_RPM
            if not rpm.exists():
                download = temporary / LDAP_RPM
                with urllib.request.urlopen(LDAP_URL, timeout=60) as response, download.open("xb") as stream:
                    data = response.read(4 * 1024**2 + 1)
                    if len(data) > 4 * 1024**2:
                        parser.error("Wine LDAP package exceeds its download limit")
                    stream.write(data)
                rpm = download
            if sha(rpm) != LDAP_SHA256:
                parser.error("Wine LDAP RPM differs from the pinned producer package")
            runtime = temporary / "runtime"
            runtime.mkdir()
            with subprocess.Popen(["rpm2cpio", str(rpm)], stdout=subprocess.PIPE) as process:
                extract_cpio(process.stdout, runtime)
                if process.wait(timeout=30):
                    parser.error("Wine LDAP RPM extraction failed")
            dll = runtime / "lib64/wine-wow64/wine/i386-windows/wldap32.dll"
            if sha(dll) != LDAP_DLL_SHA256:
                parser.error("Wine LDAP DLL differs from the pinned 32-bit file")
            for source, target in [(rpm, destination / LDAP_RPM), (dll, destination / "wldap32.dll")]:
                if target.exists():
                    if target.is_symlink() or sha(target) != sha(source):
                        parser.error("existing dependency differs: " + str(target))
                else:
                    shutil.copyfile(source, target)
        fonts = temporary / "fonts"
        fonts.mkdir()
        for name, digest in FONT_PACKAGES.items():
            package = (args.font_cache / name) if args.font_cache else destination / name
            if not package.exists():
                package = temporary / name
                url = "https://github.com/pushcx/corefonts/raw/master/" + name
                with urllib.request.urlopen(url, timeout=60) as response:
                    data = response.read(1024**2 + 1)
                if len(data) > 1024**2:
                    parser.error("font installer exceeds its download limit")
                package.write_bytes(data)
            if sha(package) != digest:
                parser.error("font installer differs from the pinned upstream Winetricks input: " + name)
            extracted_fonts = temporary / (name + "-extracted")
            subprocess.run(["7z", "e", "-y", str(package), "-o" + str(extracted_fonts)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)
            for font in extracted_fonts.iterdir():
                if font.suffix.lower() == ".ttf":
                    shutil.copyfile(font, fonts / font.name.lower())
            cached = destination / name
            if cached.exists():
                if cached.is_symlink() or sha(cached) != digest:
                    parser.error("existing font installer differs: " + str(cached))
            else:
                shutil.copyfile(package, cached)
        staged_fonts = destination / "fonts"
        if staged_fonts.exists():
            if staged_fonts.is_symlink() or files(staged_fonts) != files(fonts):
                parser.error("existing staged fonts differ; preserved without modification")
        else:
            fonts.rename(staged_fonts)
    print("Verified MyHarmony 1.0.308 application payload:", app)


if __name__ == "__main__":
    main()
