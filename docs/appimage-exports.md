# AppImage desktop proof of concept

Cage exports the same pinned portable Notepad++ recipes as Flatpak and AppImage,
using the existing ordered build pipeline and shared Wine-prefix launcher. There
is no second application installer or recipe language. Container builds remain
the default. AppImage export is experimental and qualifies one application, not
arbitrary Windows software.

## Target and dependencies

There are separate Linux x86_64 and aarch64 packages. ARM uses the same Wine
11.20 ARM64EC and FEX 2610 payload as Cage's ARM Flatpak/container profile; x86
uses the existing Wine 11.0 desktop profile. ARM accepts 4 KB and 16 KB kernels.
No host Wine, FEX, Cage, Python, Flatpak or container engine is needed to run the
resulting AppImage. A normal Linux desktop with `/bin/sh`, `/usr/bin/env`,
X11/XWayland, and executable temporary storage is required. The AppImage carries
its own glibc and matching dynamic loader from the exact pinned Freedesktop
platform. Host glibc 2.35 is an explicit consumer test target; no host libc
replacement is needed. This does not replace the host kernel or device drivers.

The build uses Flatpak to acquire the existing pinned Wine payload and
Freedesktop library sources. `readelf` resolves native imports without executing
`ldd`; a bounded list covers Wine's qualified X11/font/TLS libraries loaded
dynamically. The build fails for unresolved required dependencies and for
imports newer than the private runtime's declared glibc ceiling. `patchelf` adds
private library paths and reserves ELF interpreter slots at export time. At
launch, bundled Python creates an exclusive temporary tree, copies and verifies
the native ELF files, and fills executable interpreter slots with the mounted
package's loader path. Native libraries are copied too because Wine canonicalizes
their paths to locate child loaders. Windows payloads and other data remain
linked to the immutable package.
This covers Wine's native child processes and wineserver while retaining correct
executable identity and supporting relocated packages. Consumers need no patching
tools. The temporary tree is removed after normal application shutdown. Host
commands do not inherit the packaged libc through `LD_LIBRARY_PATH`.

The AppImage-only profile omits the Unix `winedmo.so` module: FFmpeg-backed
DirectShow decoding is outside this text-editor proof and would add an
unnecessary codec stack, including x86 imports requiring glibc 2.44. The
exclusion and original module hashes are recorded in the target/receipt;
Flatpak and container payloads are unchanged. Wine's optional camera, Kerberos
and packet-capture modules can have unavailable
libraries, enumerated in `native-dependencies.json`; those features are not
qualified. Host graphics libraries/drivers remain host-owned. GPU, audio,
printing, native Wayland, CFW and other apps need separate qualification.

`runtime/appimage-tools.json` pins the Type 2 runtime and standalone Python
archives by versioned public URL and SHA-256. The exported receipt records those
inputs, native dependency inventory, Wine and platform commits, original recipe
and seed identities, package hash and build tool version. Wine/Python notices
remain in their payloads; Freedesktop license notices and component source
references are included. Public redistribution and corresponding-source
publication remain a later release task. No commercial service is required.

## Build and export

Producer tools: Cage's normal Python dependencies, Flatpak, `readelf` from
binutils, `patchelf`, and `mksquashfs` with zstd support. ARM also uses the existing build-only
`rpm2cpio`. Produce each architecture on a native Linux builder; cross-building
or relabeling an x86 package as ARM is unsupported.

```sh
python3 scripts/prepare-flatpak-poc.py
python3 -m cage build recipes/notepadplusplus-portable-arm64.cage.yaml \
  --target appimage --flatpak-store .cage/flatpak-arm64 --output dist/appimage-bundles
python3 -m cage export appimage \
  dist/appimage-bundles/notepadplusplus-portable-arm64-8.8.8 \
  --allow-host-access --flatpak-store .cage/flatpak-arm64 \
  --output dist/notepadplusplus-8.8.8-aarch64.AppImage
```

For x86_64 use `notepadplusplus-portable.cage.yaml` and `.cage/flatpak` instead.
`--target appimage` builds the sealed portable seed in the existing pinned
Wine/Flatpak producer. Its source execution-target receipt stays accurate;
AppImage export records a distinct adapter target and retains the producer
identity. An existing matching, verified desktop bundle can also be exported
without rebuilding its application. A container-produced bundle is not silently
promoted to desktop compatibility.

`cage export appimage ... --dry-run --allow-host-access` prints the plan without
creating directories or downloading tools. Export creates a new staging context
and a new output; it refuses to overwrite either. Interrupted output assembly
uses a `.partial` file. Staging is retained for inspection.

## Permissions and desktop integration

An AppImage runs with the user's ordinary filesystem and network access. It
cannot enforce a recipe's `runtime.network: none`, Flatpak permissions or a
container sandbox. **Export refuses by default.** `--allow-host-access` is an
explicit policy exception for that export; the plan reports host access and
that the recipe's network isolation is unenforced. It does not rewrite or relax
the original recipe, Flatpak export, or container policy. Wine's Z: mapping in
this format exposes the user's accessible host filesystem, not a sandbox.

```sh
chmod +x notepadplusplus-8.8.8-aarch64.AppImage
./notepadplusplus-8.8.8-aarch64.AppImage "$HOME/Documents/example.txt"
./notepadplusplus-8.8.8-aarch64.AppImage --cage-info
./notepadplusplus-8.8.8-aarch64.AppImage --cage-install
```

Installation is optional. It copies the image to a stable per-user path under
`$XDG_DATA_HOME/cage/appimages/<app-id>/application.AppImage`, installs an icon
and menu entry with an AppImage-specific desktop ID, and safely quotes spaces,
Unicode and desktop field-code characters. It sets no default file associations
and coexists with the Flatpak's menu entry. Desktop installation refuses an
existing installation rather than pretending to support upgrades.

Run the installed image with `--cage-uninstall` to remove its verified package,
icon and menu entry. If installed files were edited or replaced, removal refuses
and retains them for recovery. Uninstall never deletes application settings or
documents. Use `--` before a file name that starts with a Cage control option.

FUSE mounts the package read-only. Where FUSE is unavailable, use the standard
extraction fallback with ample **disk-backed** temporary storage:

```sh
mkdir -p "$HOME/.cache/cage-appimage-tmp"
chmod 700 "$HOME/.cache/cage-appimage-tmp"
TMPDIR="$HOME/.cache/cage-appimage-tmp" \
  ./notepadplusplus-8.8.8-aarch64.AppImage --appimage-extract-and-run
```

`APPIMAGE_EXTRACT_AND_RUN=1` is equivalent and also works with the Cage controls.
The ARM payload currently expands to several gigabytes: allow at least 6 GB of
scratch space plus about 2.4 GB for its writable prefix. The upstream runtime
can retain extracted caches in that directory; remove those caches only after
the application has closed. Test drivers clean their dedicated temporary
directories and retain application state and evidence. A small `/tmp` tmpfs can
leave a partial upstream runtime extraction. Retain user state and retry using
an empty disk-backed temporary directory; FUSE avoids extracting the payload.
A `noexec` location cannot launch the image or an extracted executable; move it
to an executable filesystem. A mounted AppImage and its extracted AppDir both
use relative runtime paths and may move between launches.

## State and updates

The shared launcher copies the inventory-verified seed atomically on first use,
locks initialization and application launch, and scopes Wine service cleanup to
that prefix. Files passed on the command line become Windows Z: paths; the
recipe's Windows working directory and arguments remain unchanged.

AppImage state is `$XDG_DATA_HOME/cage/appimage/<app-id>/`. It is deliberately
separate from Flatpak and container prefixes. Relaunch and package relocation
reuse this state. Seed/runtime changes refuse launch while retaining the old
prefix. Explicit qualified generation updates and rollback are described in
[safe export updates](export-updates.md).
Do not share a live prefix between formats or replace the only copy of user
state to work around a mismatch. Application self-updates are not a qualified
package update mechanism.

## Qualification

`scripts/test-appimage-poc.py` checks actual menu installation, a Unicode file,
edit/save/close, settings persistence, package relocation, relaunch/second save,
unchanged package identity and uninstall retaining data. Its FUSE and
extract-and-run modes run in a private X11 desktop. The driver uses Python/GUI
test tools; these are not consumer application dependencies.

`scripts/test-appimage-consumer-poc.py` executes the actual package in a clean
Fedora/Ubuntu userland without installed Wine or Python, sharing only the test
X server and dedicated writable test paths. CI builds both architectures and
checks save/relaunch and relocation on both distro families, including pinned
Ubuntu 22.04 consumers that assert host glibc 2.35. Live process maps verify that
Wine and wineserver use the private libc. Such container userland checks
are not booted-device or GPU qualification. Physical Asahi FUSE/fallback checks
are recorded separately. See [qualification evidence](appimage-qualification.md)
for exact tested identities and outstanding limits.

## Updates and rollback

See [safe export updates](export-updates.md) for qualified migrations, retained
AppImage versions, menu dispatch, rollback and recovery. Existing pre-generation
integration must be reinstalled with a generation-aware baseline first.
