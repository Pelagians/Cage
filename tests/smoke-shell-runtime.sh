#!/bin/bash
# Exercise Wine through Cage's real inherited /init and consumer hook.
set -Eeuo pipefail
engine=${CONTAINER_ENGINE:-docker}
image=${1:?image required}
# Pin the shared test contract separately from the production Shell image.
shell_revision=a9c6100aabc0cb79deb43910e92639f9b92b4a3d
shell_source=$(mktemp -d)
git -C "$shell_source" init -q
git -C "$shell_source" fetch -q --depth 1 https://github.com/Pelagians/pelagian-shell.git "$shell_revision"
test "$(git -C "$shell_source" rev-parse FETCH_HEAD)" = "$shell_revision"
git -C "$shell_source" checkout -q --detach FETCH_HEAD
conformance="$shell_source/tests/consumer-conformance"
name="cage-shell-smoke-$$"
# shellcheck disable=SC2317,SC2329
cleanup() {
    result=$?
    trap - EXIT
    if (( result != 0 )); then
        "$engine" logs "$name" >&2 || true
        # The container shell expands diagnostic paths.
        # shellcheck disable=SC2016
        "$engine" exec "$name" sh -c 'for f in /config/.local/state/pelagian-shell/*.log; do test ! -f "$f" || tail -n 80 "$f"; done' >&2 || true
    fi
    "$engine" rm -f "$name" >/dev/null 2>&1 || true
    "$engine" volume rm -f "$name-config" >/dev/null 2>&1 || true
    rm -rf "$shell_source"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
# Expanded inside the consumer's session, not by the host.
# shellcheck disable=SC2016
script='set -Eeuo pipefail
export WINEPREFIX=/tmp/cage-prefix/shell-smoke
mkdir -p "$WINEPREFIX"
export WINEDLLOVERRIDES="mscoree,mshtml="
wineboot --init
/usr/local/libexec/cage-select-wine-graphics
wine reg query "HKCU\Control Panel\Colors" /v Window | grep -q "24 26 29"
exec wine notepad'
encoded=$(printf '%s' "$script" | base64 -w0)
"$engine" volume create "$name-config" >/dev/null
"$engine" run -d --name "$name" --shm-size=2g \
    --env "PUID=$(id -u)" --env "PGID=$(id -g)" \
    --env CAGE_SESSION_MODE=selkies --env CAGE_WINE_GRAPHICS=xwayland \
    --env "CAGE_LAUNCH_SCRIPT_B64=$encoded" \
    --env SELKIES_MANUAL_WIDTH=1920 --env SELKIES_MANUAL_HEIGHT=1080 \
    --volume "$name-config:/config" "$image" >/dev/null
"$engine" cp "$conformance/verify-shell-session.py" "$name:/tmp/verify-shell-session.py"
CONTAINER_ENGINE="$engine" "$conformance/start-shell-stream.sh" "$name" "$shell_source/tests/selkies-smoke-client.py"
"$engine" exec --user abc "$name" python3 /tmp/verify-shell-session.py notepad
printf 'Cage Wine shell smoke: PASS image=%s engine=%s\n' "$image" "$engine"
