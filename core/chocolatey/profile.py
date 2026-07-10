"""Versioned Chocolatey bootstrap profiles."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import re

from core.powershell_wrapper_assets import (
    POWERSHELL_WRAPPER_BASE_URL,
    POWERSHELL_WRAPPER_SHA256,
    POWERSHELL_WRAPPER_VERSION,
)


class ChocolateyProfileError(ValueError):
    """Raised when a Chocolatey bootstrap profile is invalid or unknown."""


DEFAULT_BOOTSTRAP_PROFILE_ID = "cfw-v0.5c.755-choco-2.6.0-upstream-r6"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ChocolateyBootstrapProfile:
    """One tested, immutable Chocolatey-for-Wine compatibility set."""

    id: str
    chocolatey_for_wine_version: str
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
    powershell_host_feature: str = "powershellHost"
    powershell_host: str = "disabled"
    allow_global_confirmation: str = "disabled"
    mscoree_update_url: str = "https://catalog.s.download.windowsupdate.com/msdownload/update/software/crup/2010/06/windows6.1-kb958488-v6001-x64_a137e4f328f01146dfa75d7b5a576090dee948dc.msu"
    mscoree_update_sha256: str = "a5f4243ce8b07c9222284fd8ff6f7e742d934c57c89de9cab5d88c74402264e3"
    powershell_wrapper_version: str = POWERSHELL_WRAPPER_VERSION
    powershell_wrapper_base_url: str = POWERSHELL_WRAPPER_BASE_URL
    powershell_wrapper64_sha256: str = POWERSHELL_WRAPPER_SHA256["powershell64.exe"]
    powershell_wrapper32_sha256: str = POWERSHELL_WRAPPER_SHA256["powershell32.exe"]
    powershell_wrapper_profile_sha256: str = POWERSHELL_WRAPPER_SHA256["profile.ps1"]

    def validate(self) -> None:
        if not self.id or not self.dotnet_profile or not self.revision:
            raise ChocolateyProfileError("Chocolatey bootstrap profile identity is incomplete")
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
            "powershellWrapperVersion": self.powershell_wrapper_version,
            "powershellWrapperBaseUrl": self.powershell_wrapper_base_url,
            "powershellWrapper64Sha256": self.powershell_wrapper64_sha256,
            "powershellWrapper32Sha256": self.powershell_wrapper32_sha256,
            "powershellWrapperProfileSha256": self.powershell_wrapper_profile_sha256,
            "features": {
                "powershellHostFeature": self.powershell_host_feature,
                "powershellHost": self.powershell_host,
                "allowGlobalConfirmation": self.allow_global_confirmation,
            },
            "upstreamProject": self.upstream_project,
            "upstreamTag": self.upstream_tag,
            "revision": self.revision,
        }

    def template_values(self) -> dict[str, str]:
        return {
            "BOOTSTRAP_PROFILE_ID": self.id,
            "CHOCOLATEY_FOR_WINE_VERSION": self.chocolatey_for_wine_version,
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
            "POWERSHELL_WRAPPER_VERSION": self.powershell_wrapper_version,
            "POWERSHELL_WRAPPER_BASE_URL": self.powershell_wrapper_base_url,
            "POWERSHELL_WRAPPER64_SHA256": self.powershell_wrapper64_sha256,
            "POWERSHELL_WRAPPER32_SHA256": self.powershell_wrapper32_sha256,
            "POWERSHELL_WRAPPER_PROFILE_SHA256": self.powershell_wrapper_profile_sha256,
            "POWERSHELL_HOST_FEATURE": self.powershell_host_feature,
            "POWERSHELL_HOST_POLICY": self.powershell_host,
            "ALLOW_GLOBAL_CONFIRMATION_POLICY": self.allow_global_confirmation,
        }


_BUILTIN_PROFILES = {
    DEFAULT_BOOTSTRAP_PROFILE_ID: ChocolateyBootstrapProfile(
        id=DEFAULT_BOOTSTRAP_PROFILE_ID,
        chocolatey_for_wine_version="v0.5c.755",
        chocolatey_for_wine_url="https://github.com/PietJankbal/Chocolatey-for-wine/releases/download/v0.5c.755/Chocolatey-for-wine.7z",
        chocolatey_for_wine_sha256="87f4ecc08a9b22f16aa5633ca107c151ddf3fed0b256fed9fb99680af7095d14",
        winetricks_ps1_url="https://raw.githubusercontent.com/PietJankbal/Chocolatey-for-wine/v0.5c.755/winetricks.ps1",
        winetricks_ps1_sha256="1d74ffad96f2052d42a0fa3c7ac5dbc8d099e7ad9f9aba3213446a25b34ff48c",
        chocolatey_version="2.6.0",
        chocolatey_nupkg_url="https://community.chocolatey.org/api/v2/package/chocolatey/2.6.0",
        chocolatey_nupkg_sha256="f13a2af9cd4ec2c9b58d81861bc95ad7151e3a871d8f758dffa72a996a3792d8",
        powershell_version="7.5.5",
        powershell_msi_name="PowerShell-7.5.5-win-x64.msi",
        powershell_msi_url="https://github.com/PowerShell/PowerShell/releases/download/v7.5.5/PowerShell-7.5.5-win-x64.msi",
        powershell_msi_sha256="b2ac56b7639e2b259bb78bab077555d76f2a5eec6c516690d63de36bc1d6ca25",
        powershell_msi_product_code="634F4903-28DC-4BA6-A39F-4B3E394D4E36",
        dotnet_profile="dotnet481-cfw-r1",
        dotnet_installer_url="https://download.visualstudio.microsoft.com/download/pr/6f083c7e-bd40-44d4-9e3f-ffba71ec8b09/3951fd5af6098f2c7e8ff5c331a0679c/ndp481-x86-x64-allos-enu.exe",
        dotnet_installer_sha256="859b556ee19a33353626682b8b6f7e9ce97cd325b0d8f24c7770dc31f688d3c1",
        upstream_project="PietJankbal/Chocolatey-for-wine",
        upstream_tag="v0.5c.755",
        revision="r6",
    ),
}


def get_bootstrap_profile(profile_id: str = DEFAULT_BOOTSTRAP_PROFILE_ID) -> ChocolateyBootstrapProfile:
    try:
        profile = _BUILTIN_PROFILES[profile_id]
    except KeyError as exc:
        raise ChocolateyProfileError(f"unknown Chocolatey bootstrap profile: {profile_id}") from exc
    profile.validate()
    return profile
