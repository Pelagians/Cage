#!/bin/sh
# Cage Wine Environment Setup
# Source this in Dockerfile RUN commands or entrypoints to standardize the
# Wine environment.  Sets WINEPREFIX, common overrides, and font paths.
#
# Usage:  . /opt/cage/common/wine-env.sh

: "${WINEPREFIX:=/opt/cage/prefix}"
: "${WINEDEBUG:=-all}"
: "${WINEDLLOVERRIDES:=mscoree,mshtml=}"
: "${WINEARCH:=win64}"

export WINEPREFIX WINEDEBUG WINEDLLOVERRIDES WINEARCH

# Use bundled fonts when available
if [ -d "/opt/cage/share/fonts" ]; then
    export FREETYPE_PROPERTIES="truetype:interpreter-version=35"
fi
