#!/usr/bin/env bash
# Cage UMU runtime entrypoint.
#
# UMU refuses to run as root and also requires the effective UID to resolve
# through getpwuid(3). Container engines can set a numeric UID, but that does
# not create a passwd entry. Start as root, materialize the requested identity,
# prepare its writable home, then drop privileges before Xvfb or UMU starts.
set -euo pipefail

: "${CAGE_RUNTIME_UID:=1000}"
: "${CAGE_RUNTIME_GID:=1000}"
: "${CAGE_RUNTIME_USER:=cage}"
: "${CAGE_RUNTIME_HOME:=/opt/cage/.runtime-home}"

if [ "$(id -u)" -ne 0 ]; then
    export HOME="${HOME:-$CAGE_RUNTIME_HOME}"
    exec /usr/local/bin/xvfb-entrypoint.sh "$@"
fi

case "$CAGE_RUNTIME_UID:$CAGE_RUNTIME_GID" in
    *[!0-9:]*|:*|*:) echo "invalid Cage runtime UID/GID" >&2; exit 64 ;;
esac
if [ "$CAGE_RUNTIME_UID" -eq 0 ]; then
    echo "CAGE_RUNTIME_UID must be non-zero for UMU" >&2
    exit 64
fi

runtime_group="$(getent group "$CAGE_RUNTIME_GID" | cut -d: -f1 || true)"
if [ -z "$runtime_group" ]; then
    runtime_group="${CAGE_RUNTIME_USER}-${CAGE_RUNTIME_GID}"
    groupadd --gid "$CAGE_RUNTIME_GID" "$runtime_group"
fi

runtime_user="$(getent passwd "$CAGE_RUNTIME_UID" | cut -d: -f1 || true)"
if [ -z "$runtime_user" ]; then
    runtime_user="${CAGE_RUNTIME_USER}-${CAGE_RUNTIME_UID}"
    useradd \
        --uid "$CAGE_RUNTIME_UID" \
        --gid "$CAGE_RUNTIME_GID" \
        --home-dir "$CAGE_RUNTIME_HOME" \
        --shell /bin/bash \
        --no-create-home \
        "$runtime_user"
fi

mkdir -p "$CAGE_RUNTIME_HOME"
chown "$CAGE_RUNTIME_UID:$CAGE_RUNTIME_GID" "$CAGE_RUNTIME_HOME"
export HOME="$CAGE_RUNTIME_HOME"

exec gosu "$CAGE_RUNTIME_UID:$CAGE_RUNTIME_GID" \
    /usr/local/bin/xvfb-entrypoint.sh "$@"
