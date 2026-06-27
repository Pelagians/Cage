#!/bin/sh
# WinForge Wine Environment Setup
# Source this in Dockerfile RUN commands or entrypoints to standardize the
# Wine environment.  Sets WINEPREFIX, common overrides, and font paths.
#
# Usage:  . /opt/winforge/common/wine-env.sh

: "${WINEPREFIX:=/opt/winforge/prefix}"
: "${WINEDEBUG:=-all}"
: "${WINEDLLOVERRIDES:=mscoree,mshtml=}"
: "${WINEARCH:=win64}"

export WINEPREFIX WINEDEBUG WINEDLLOVERRIDES WINEARCH

# Use bundled fonts when available
if [ -d "/opt/winforge/share/fonts" ]; then
    export FREETYPE_PROPERTIES="truetype:interpreter-version=35"
fi
