#!/bin/sh
set -eu
if [ "$(id -u)" != 0 ]; then
    echo "Run once with: sudo sh install-usb-rules.sh" >&2
    exit 1
fi
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
command -v udevadm >/dev/null
install -D -m 0644 "$here/70-cage-myharmony.rules" /etc/udev/rules.d/70-cage-myharmony.rules
udevadm control --reload-rules
echo "Harmony USB access installed. Unplug and reconnect the remote or hub. Run the AppImage as your regular desktop user."
