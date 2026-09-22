#!/bin/bash
# Start the upstream viewer: an HTTP request alone does not drive frame callbacks.
set -Eeuo pipefail
engine=${CONTAINER_ENGINE:-docker}
name=${1:?container name required}
client=$(mktemp)
trap 'rm -f "$client"' EXIT
revision=3a17b6be5e3d8f27dc53ff00566dc56b90c4fa27
curl --fail --silent --show-error --retry 3 \
    "https://raw.githubusercontent.com/Pelagians/pelagian-shell/$revision/tests/selkies-smoke-client.py" > "$client"
printf '%s  %s\n' cef81eb602743419b98b3c4bd4387cb1585bd97bc1ba495ab4e893e3ef407a52 "$client" | sha256sum --check --status
"$engine" cp "$client" "$name:/tmp/selkies-smoke-client.py"
"$engine" exec "$name" chmod 0644 /tmp/selkies-smoke-client.py
for _ in $(seq 1 120); do
    if "$engine" exec "$name" curl -kfsS --max-time 2 https://127.0.0.1:3001/ >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
"$engine" exec --user abc "$name" rm -rf /tmp/pelagian-stream-smoke
# nginx can serve the page before its WebSocket route/backend is ready.
# Retry only handshake startup failures, never a failed decoded-frame assertion.
# shellcheck disable=SC2016
"$engine" exec -d --user abc "$name" sh -c '
    for attempt in $(seq 1 30); do
        /lsiopy/bin/python /tmp/selkies-smoke-client.py 1920 1080 > /tmp/pelagian-stream-smoke.log 2>&1
        test ! -e /tmp/pelagian-stream-smoke/ready || exit 1
        grep -Eq "HTTP (404|502|503)|ConnectionRefusedError|timed out during opening handshake" /tmp/pelagian-stream-smoke.log || exit 1
        sleep 1
    done
    exit 1
'
for _ in $(seq 1 90); do
    if "$engine" exec "$name" test -s /tmp/pelagian-stream-smoke/ready; then
        "$engine" exec "$name" cat /tmp/pelagian-stream-smoke/ready
        exit 0
    fi
    sleep 1
done
"$engine" exec "$name" cat /tmp/pelagian-stream-smoke.log >&2
exit 1
