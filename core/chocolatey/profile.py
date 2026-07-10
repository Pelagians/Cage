"""Versioned Chocolatey bootstrap profiles."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import re


class ChocolateyProfileError(ValueError):
    """Raised when a Chocolatey bootstrap profile is invalid or unknown."""


DEFAULT_BOOTSTRAP_PROFILE_ID = "cfw-v0.5c.755-noah.2-choco-2.6.0-fork-r8"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTALLER_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ChocolateyBootstrapProfile:
    """One tested, immutable Chocolatey-for-Wine compatibility set."""

    id: str
    chocolatey_for_wine_version: str
    chocolatey_for_wine_installer_version: str
    chocolatey_for_wine_url: str
    chocolatey_for_wine_sha256: str
    winetricks_ps1_url: str
    winetricks_ps1_sha256: str
    chocolatey_version: str
    chocolatey_nupkg_url: str
    chocolatey_nupkg_sha256: str
    powershell_version: str
    powershell_msi_name: str
    powershell_msi_url: str
    powershell_msi_sha256: str
    powershell_msi_product_code: str
    dotnet_profile: str
    dotnet_installer_url: str
    dotnet_installer_sha256: str
    upstream_project: str
    upstream_tag: str
    revision: str
    d3dcompiler47_url: str
    d3dcompiler47_sha256: str
    d3dcompiler47_x86_url: str
    d3dcompiler47_x86_sha256: str
    conemu_url: str
    conemu_sha256: str
    sevenzip_extractor_url: str
    sevenzip_extractor_sha256: str
    windows_powershell_url: str
    windows_powershell_sha256: str
    powershell_host_feature: str = "powershellHost"
    powershell_host: str = "disabled"
    allow_global_confirmation: str = "disabled"
    mscoree_update_url: str = "https://catalog.s.download.windowsupdate.com/msdownload/update/software/crup/2010/06/windows6.1-kb958488-v6001-x64_a137e4f328f01146dfa75d7b5a576090dee948dc.msu"
    mscoree_update_sha256: str = "a5f4243ce8b07c9222284fd8ff6f7e742d934c57c89de9cab5d88c74402264e3"

    def validate(self) -> None:
        if not self.id or not self.dotnet_profile or not self.revision:
            raise ChocolateyProfileError("Chocolatey bootstrap profile identity is incomplete")
        if not _INSTALLER_VERSION_RE.fullmatch(self.chocolatey_for_wine_installer_version):
            raise ChocolateyProfileError("Chocolatey installer version is not a safe filename token")
        for field_name, value in asdict(self).items():
            if field_name.endswith("_url") and not value.startswith("https://"):
                raise ChocolateyProfileError(f"Chocolatey bootstrap profile {field_name} must use https")
            if field_name.endswith("_sha256") and not _SHA256_RE.fullmatch(value):
                raise ChocolateyProfileError(
                    f"Chocolatey bootstrap profile {field_name} must be a complete sha256"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chocolateyForWineVersion": self.chocolatey_for_wine_version,
            "chocolateyForWineInstallerVersion": self.chocolatey_for_wine_installer_version,
            "chocolateyForWineUrl": self.chocolatey_for_wine_url,
            "chocolateyForWineSha256": self.chocolatey_for_wine_sha256,
            "winetricksPs1Url": self.winetricks_ps1_url,
            "winetricksPs1Sha256": self.winetricks_ps1_sha256,
            "chocolateyVersion": self.chocolatey_version,
            "chocolateyNupkgUrl": self.chocolatey_nupkg_url,
            "chocolateyNupkgSha256": self.chocolatey_nupkg_sha256,
            "powershellVersion": self.powershell_version,
            "powershellMsiName": self.powershell_msi_name,
            "powershellMsiUrl": self.powershell_msi_url,
            "powershellMsiSha256": self.powershell_msi_sha256,
            "powershellMsiProductCode": self.powershell_msi_product_code,
            "dotnetProfile": self.dotnet_profile,
            "dotnetInstallerUrl": self.dotnet_installer_url,
            "dotnetInstallerSha256": self.dotnet_installer_sha256,
            "mscoreeUpdateUrl": self.mscoree_update_url,
            "mscoreeUpdateSha256": self.mscoree_update_sha256,
            "features": {
                "powershellHostFeature": self.powershell_host_feature,
                "powershellHost": self.powershell_host,
                "allowGlobalConfirmation": self.allow_global_confirmation,
            },
            "upstreamProject": self.upstream_project,
            "upstreamTag": self.upstream_tag,
            "revision": self.revision,
            "d3dcompiler47Url": self.d3dcompiler47_url,
            "d3dcompiler47Sha256": self.d3dcompiler47_sha256,
            "d3dcompiler47X86Url": self.d3dcompiler47_x86_url,
            "d3dcompiler47X86Sha256": self.d3dcompiler47_x86_sha256,
            "conemuUrl": self.conemu_url,
            "conemuSha256": self.conemu_sha256,
            "sevenzipExtractorUrl": self.sevenzip_extractor_url,
            "sevenzipExtractorSha256": self.sevenzip_extractor_sha256,
            "windowsPowershellUrl": self.windows_powershell_url,
            "windowsPowershellSha256": self.windows_powershell_sha256,
        }

    def template_values(self) -> dict[str, str]:
        return {
            "BOOTSTRAP_PROFILE_ID": self.id,
            "CHOCOLATEY_FOR_WINE_VERSION": self.chocolatey_for_wine_version,
            "CHOCOLATEY_FOR_WINE_INSTALLER_VERSION": self.chocolatey_for_wine_installer_version,
            "CHOCOLATEY_FOR_WINE_URL": self.chocolatey_for_wine_url,
            "CHOCOLATEY_FOR_WINE_SHA256": self.chocolatey_for_wine_sha256,
            "WINETRICKS_PS1_URL": self.winetricks_ps1_url,
            "WINETRICKS_PS1_SHA256": self.winetricks_ps1_sha256,
            "CHOCOLATEY_VERSION": self.chocolatey_version,
            "CHOCOLATEY_NUPKG_URL": self.chocolatey_nupkg_url,
            "CHOCOLATEY_NUPKG_SHA256": self.chocolatey_nupkg_sha256,
            "POWERSHELL_VERSION": self.powershell_version,
            "POWERSHELL_MSI_NAME": self.powershell_msi_name,
            "POWERSHELL_MSI_URL": self.powershell_msi_url,
            "POWERSHELL_MSI_SHA256": self.powershell_msi_sha256,
            "POWERSHELL_MSI_PRODUCT_CODE": self.powershell_msi_product_code,
            "DOTNET_PROFILE": self.dotnet_profile,
            "DOTNET_INSTALLER_URL": self.dotnet_installer_url,
            "DOTNET_INSTALLER_SHA256": self.dotnet_installer_sha256,
            "MSCOREE_UPDATE_URL": self.mscoree_update_url,
            "MSCOREE_UPDATE_SHA256": self.mscoree_update_sha256,
            "POWERSHELL_HOST_FEATURE": self.powershell_host_feature,
            "POWERSHELL_HOST_POLICY": self.powershell_host,
            "ALLOW_GLOBAL_CONFIRMATION_POLICY": self.allow_global_confirmation,
            "D3DCOMPILER47_URL": self.d3dcompiler47_url,
            "D3DCOMPILER47_SHA256": self.d3dcompiler47_sha256,
            "D3DCOMPILER47_X86_URL": self.d3dcompiler47_x86_url,
            "D3DCOMPILER47_X86_SHA256": self.d3dcompiler47_x86_sha256,
            "CONEMU_URL": self.conemu_url,
            "CONEMU_SHA256": self.conemu_sha256,
            "SEVENZIP_EXTRACTOR_URL": self.sevenzip_extractor_url,
            "SEVENZIP_EXTRACTOR_SHA256": self.sevenzip_extractor_sha256,
            "WINDOWS_POWERSHELL_URL": self.windows_powershell_url,
            "WINDOWS_POWERSHELL_SHA256": self.windows_powershell_sha256,
        }


_BUILTIN_PROFILES = {
    DEFAULT_BOOTSTRAP_PROFILE_ID: ChocolateyBootstrapProfile(
        id=DEFAULT_BOOTSTRAP_PROFILE_ID,
        chocolatey_for_wine_version="v0.5c.755-noah.2",
        chocolatey_for_wine_installer_version="0.5c.755",
        chocolatey_for_wine_url="https://github.com/noahgiroux/Chocolatey-for-wine/releases/download/v0.5c.755-noah.2/Chocolatey-for-wine.7z",
        chocolatey_for_wine_sha256="b973ca8557449d64791f82b724aea1ecc4d6a91d11d6c401f92a7ce33cb9029f",
        winetricks_ps1_url="https://raw.githubusercontent.com/noahgiroux/Chocolatey-for-wine/5e81fe29f1ecfabf1618e810d9af65504db4eda7/winetricks.ps1",
        winetricks_ps1_sha256="1d74ffad96f2052d42a0fa3c7ac5dbc8d099e7ad9f9aba3213446a25b34ff48c",
        chocolatey_version="2.6.0",
        chocolatey_nupkg_url="https://community.chocolatey.org/api/v2/package/chocolatey/2.6.0",
        chocolatey_nupkg_sha256="f13a2af9cd4ec2c9b58d81861bc95ad7151e3a871d8f758dffa72a996a3792d8",
        powershell_version="7.5.5",
        powershell_msi_name="PowerShell-7.5.5-win-x64.msi",
        powershell_msi_url="https://github.com/PowerShell/PowerShell/releases/download/v7.5.5/PowerShell-7.5.5-win-x64.msi",
        powershell_msi_sha256="b2ac56b7639e2b259bb78bab077555d76f2a5eec6c516690d63de36bc1d6ca25",
        powershell_msi_product_code="634F4903-28DC-4BA6-A39F-4B3E394D4E36",
        dotnet_profile="dotnet48-cfw-r1",
        dotnet_installer_url="https://download.visualstudio.microsoft.com/download/pr/7afca223-55d2-470a-8edc-6a1739ae3252/abd170b4b0ec15ad0222a809b761a036/ndp48-x86-x64-allos-enu.exe",
        dotnet_installer_sha256="95889d6de3f2070c07790ad6cf2000d33d9a1bdfc6a381725ab82ab1c314fd53",
        upstream_project="noahgiroux/Chocolatey-for-wine",
        upstream_tag="v0.5c.755-noah.2",
        revision="r8",
        d3dcompiler47_url="https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47.dll",
        d3dcompiler47_sha256="4432bbd1a390874f3f0a503d45cc48d346abc3a8c0213c289f4b615bf0ee84f3",
        d3dcompiler47_x86_url="https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47_32.dll",
        d3dcompiler47_x86_sha256="2ad0d4987fc4624566b190e747c9d95038443956ed816abfd1e2d389b5ec0851",
        conemu_url="https://github.com/Maximus5/ConEmu/releases/download/v23.07.24/ConEmuPack.230724.7z",
        conemu_sha256="2a9b98ebecaede62665ef427b05b3a5ccdac7bd3202414fc0f4c10825b4f4ea2",
        sevenzip_extractor_url="https://globalcdn.nuget.org/packages/sevenzipextractor.1.0.19.nupkg",
        sevenzip_extractor_sha256="c660063da7a343115272de59591597d8cc12d320957b1636a210524d6a67b95b",
        windows_powershell_url="https://catalog.s.download.windowsupdate.com/msdownload/update/software/updt/2009/11/windowsserver2003-kb968930-x64-eng_8ba702aa016e4c5aed581814647f4d55635eff5c.exe",
        windows_powershell_sha256="9f5d24517f860837daaac062e5bf7e6978ceb94e4e9e8567798df6777b56e4c8",
    ),
}


def get_bootstrap_profile(profile_id: str = DEFAULT_BOOTSTRAP_PROFILE_ID) -> ChocolateyBootstrapProfile:
    try:
        profile = _BUILTIN_PROFILES[profile_id]
    except KeyError as exc:
        raise ChocolateyProfileError(f"unknown Chocolatey bootstrap profile: {profile_id}") from exc
    profile.validate()
    return profile
