# MyHarmony for Linux x86_64

Make the download executable (`chmod +x MyHarmony-1.0.308-x86_64.AppImage`)
and start it as your regular desktop user.
It opens MyHarmony in its own normal window. Internet access is required for
Logitech's hosted interface and account service.

This build needs Linux x86_64, X11 or XWayland, and executable temporary
storage. Wine, Python, glibc and its matching loader are bundled. The build
tests the application on an Ubuntu 22.04 userland with host glibc 2.35; a
system libc upgrade is unnecessary. CI verifies native startup, relaunch and
state persistence. Logitech returns HTTP 403 to the CI runner, so its online
login screen and physical USB synchronization remain unqualified. If FUSE is unavailable:

```
APPIMAGE_EXTRACT_AND_RUN=1 ./MyHarmony-1.0.308-x86_64.AppImage
```

## USB access (one time per computer)

Keep the rules file, `manage-usb-rules.py` and the installer script together and run:

```
sudo sh install-usb-rules.sh
```

Unplug and reconnect the remote/hub using a data-capable USB cable. Then run
MyHarmony normally, without sudo. The rules use systemd-logind's `uaccess`
ACLs for the active local desktop user; no broad world-writable USB rules.
The AppImage runs directly on the host and can see newly plugged devices.

The rules cover **all 64 IDs in Logitech's Harmony range 046d:c110-c14f**
and the **older 0400:c359** identity, for both USB device nodes and hidraw.
This includes Hub c129, Touch/Ultimate c12b, 300/350 c124, 200 c125,
650/700 c122, One c121, 900/1100 c11f and earlier Harmony devices.
Family-range coverage includes unnamed IDs rather than only a short model list.
Source: [Concordance's Harmony device predicate](https://github.com/jaymzh/concordance/blob/main/libconcord/libhidapi.cpp),
cross-checked against the [USB ID Repository](https://usb-ids.gowdy.us/read/UD/046d).
No additional recovery-mode IDs outside those ranges were established.
USB permission coverage does not establish MyHarmony support for every older
model or continued availability of its Logitech service. Devices configured via
a hub use the hub's USB connection where the remote has no USB data connection.

[Logitech's current model list](https://app.myharmony.com/) identifies MyHarmony
support for 200/300/350, 600/650/665/700, 950, One, Touch, Ultimate, Elite,
Companion, Smart Control/Keyboard, Pro and their hubs. Logitech retired the
older v7 software's service in May 2025; granting USB access to those older
remotes cannot restore that service. Harmony Express uses its separate mobile app.

The packaged HID backend and USB libraries are checked during the build.
Physical detection, hotplug, recovery and synchronization require testing with
real hardware; they are not established by a GUI test without a remote.

## Saved state

Settings and login state persist under
`${XDG_DATA_HOME:-$HOME/.local/share}/cage/appimage/io.github.Pelagians.Cage.MyHarmony/`.
Keep that directory when replacing the AppImage. Deleting the AppImage does not
remove it. Do not copy credentials into bug reports.

The helper preserves modified or untracked rules, tracks owners shared by
multiple exports, and saves removed/upgraded rules under `/etc/cage/udev-rules`.
To release this application's ownership, run `sudo sh install-usb-rules.sh remove`.
The last owner removes only an unchanged Cage-created file; existing identical
administrator-owned rules remain installed. Application state is retained.

## Rebuild from the Cage checkout

```
python3 scripts/prepare-myharmony.py /path/to/MyHarmony-App.msi --runtime wine
python3 -m cage build recipes/myharmony.cage.yaml --target appimage --flatpak-store .cage/flatpak --output dist/myharmony-bundles
python3 -m cage export appimage dist/myharmony-bundles/myharmony-1.0.308 --allow-host-access --flatpak-store .cage/flatpak --output dist/MyHarmony-1.0.308-x86_64.AppImage
```

The MSI must match the pinned official MyHarmony 1.0.308 download. The preparation
script verifies the embedded application and Arial/Trebuchet font packages.
The recipe's offline build policy does not restrict the exported AppImage's host
network access. The application and font sources remain proprietary BYO inputs.

## Managed v1 candidate

The v0 AppImage instructions above describe the existing direct-host build.
The opt-in [v1 candidate](../../recipes/myharmony-compat.cage.yaml) requests
networking, X11, an optional writable folder and All Devices on all three
formats. V1 requires host Cage, an explicitly accepted capability contract and
its qualified native Ubuntu 24.04 x86_64 launch path. It does not use
`--allow-host-access`, AppRun or a Wine virtual desktop. Host uaccess rules
remain a separate explicit administrative prerequisite. See the
[implementation/qualification status](../../docs/proposals/capability-parity/implementation-status.md).
