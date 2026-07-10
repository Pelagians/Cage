"""Pinned powershell-wrapper-for-wine release assets shared by Cage providers."""
from __future__ import annotations

POWERSHELL_WRAPPER_VERSION = "v4.2.0"
POWERSHELL_WRAPPER_BASE_URL = (
    "https://codeberg.org/Synchro/powershell-wrapper-for-wine/releases/download/"
    f"{POWERSHELL_WRAPPER_VERSION}"
)
POWERSHELL_WRAPPER_SHA256 = {
    "powershell64.exe": "b1d594bd44abc01007b9dd2adea5248f09906fa8d4c6cea7f36a4279e2de91e0",
    "powershell32.exe": "ca76d774273ffa37053545f8e4ad63c8914461828f1d1eef7a1915c9656fed4c",
    "profile.ps1": "f2ae629da40bbd60f66554dc87f3145bb6ca9b2adc6eda3be515438c8bee2e24",
}

__all__ = [
    "POWERSHELL_WRAPPER_VERSION",
    "POWERSHELL_WRAPPER_BASE_URL",
    "POWERSHELL_WRAPPER_SHA256",
]
