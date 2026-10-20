# AppImage qualification

This qualifies pinned Notepad++ 8.8.8, using the existing x86 Wine 11.0 and ARM
Wine 11.20/FEX 2610 targets. It does not establish general Windows application,
GPU, CFW, or ARM hardware compatibility. The recipe files are shared with the
Flatpak and container builds; no AppImage-specific application recipe was added.

## Qualified artifacts and inputs

The local ARM package is `dist/notepadplusplus-8.8.8-aarch64.AppImage`:

- Bytes: `548604424`.
- SHA-256: `623c14a184cda362c6ab8b57cdb37ed5b911f8ac5ad909f90d6c41865f8e11a7`.
- Seed identity: `0608a39809ebae006b5200961b1aa07e1c9ccfafaf5e8b29ea90cc937658f4b9`.
- AppImage tools/profile identity: `a9802cab6aaa8aa24f956fbd18269a3d4f89bf64bc6b687b4cf4a6b5b61fd23e`.

The package includes the shared launcher, pinned standalone Python, native Wine
and FEX, selected native dependencies, pinned X11 keyboard/locale data, font data,
license notices, the application manifest and the sealed prefix seed. Platform
absolute data links are resolved inside the pinned platform, not on the producer
host. Wine's `/app` aliases become contained relative links. The AppImage-only
profile excludes the unqualified FFmpeg-backed Unix DMO module and records the
original bytes when present. Existing Flatpak/container payloads are unchanged.

Qualified implementation and GUI-driver revision:
`f544a9ebc532479df9c99e992ce330ae9ec7d0de`.

- [Native ARM and x86 AppImage proof](https://github.com/Pelagians/Cage/actions/runs/39403225349): both jobs passed.
- [Existing x86 Flatpak proof](https://github.com/Pelagians/Cage/actions/runs/39403225508): passed.
- [Existing ARM container and installed Flatpak proof](https://github.com/Pelagians/Cage/actions/runs/39403225427): passed.

Each native CI job passed the full Python suite (**466 tests and 173 subtests**).
The AppImage jobs exercised actual save/relaunch in clean Ubuntu and Fedora
consumers that have neither host-installed Wine nor Python. The packaged
interpreter and Wine run inside the consumer; the GUI driver remains outside it.

The delivered x86 package is `dist/notepadplusplus-8.8.8-x86_64.AppImage`,
`193747448` bytes, with SHA-256
`d6eef0aca077a04c764497d051dd13fa385baba811f2c46c825b3f3c2639b081`.
It was built on native x86 CI at the qualified revision. Downloaded native
artifacts and receipts are retained under `.cage/appimage-ci-qualified-{x86,arm}/`;
their hashes were checked against export receipts.

The local ARM package was assembled at `713d43ab54764650cd02192b11d42dda7b0edc40`.
All shipping exporter/runtime source files are byte-identical to the qualified
revision, which subsequently corrected only GUI test input. The local ARM
package was exercised with those corrected drivers. Native CI prefix builds
have their own seed identities, so its ARM artifact need not be byte-identical
to the local Asahi package.

A consolidated receipt and selected evidence are in ignored
`dist/appimage-qualified/qualification.json`. Source file hashes, delivered
package hashes, seeds, runtime targets and CI identities are recorded there.

## Real workflow coverage

| Architecture / kernel | Environment | Checked workflow |
| --- | --- | --- |
| ARM64 / 16 KB | Physical Fedora Asahi, private authenticated X11 desktop, FUSE | Menu installation, Unicode file, edit/save/close, zoom setting, package relocation, relaunch/second save, unchanged package, uninstall retaining state |
| ARM64 / 16 KB | Same host, extraction fallback with private disk-backed scratch | Same complete application and integration workflow |
| ARM64 / 16 KB | Clean Ubuntu 26.04 consumer on the Asahi kernel | No installed Wine/Python, actual saved text, close, reopen, second save, same prefix generation |
| ARM64 / 4 KB | Native ARM CI, Ubuntu 26.04 and Fedora 44 consumers | Native ARM package launch, actual saved text, close, reopen, second save, same prefix generation |
| x86_64 / 4 KB | Native x86 CI, Ubuntu 26.04 and Fedora 44 consumers | Native x86 package launch and the same save/relaunch workflow |

Consumer container tests qualify userspace dependency portability and actual
application behavior on the host kernel. They are **not booted Ubuntu/Fedora
hardware tests**. The physical Asahi result is recorded separately. The test
containers impose their own offline policy; that does not make the AppImage
itself a sandbox.

Local current-driver receipts, logs, selected screenshots and state are under
`dist/appimage-evidence/asahi-qualified-{fuse,extract}/` and
`dist/appimage-evidence/ubuntu-qualified/`. The source package hash was verified
after actual use, settings and prefix-generation records survived relaunch, and
menu removal retained the user state and saved documents.

## Regression and failure cases

The subsequent GUI driver revision explicitly focuses the loaded editor before
sending Ctrl+A. A retained x86 Flatpak failure screenshot showed that its first
select-all arrived before editor focus: the application correctly saved the new
line above the original document, instead of replacing the text as the test
intended. The assertion was not relaxed. The focus correction applies to all
Notepad++ GUI proofs; the updated x86 Flatpak and ARM container/Flatpak
workflows passed. The existing immutable ARM container also passed a local
Asahi save/relaunch/settings/seed-integrity check with the current Cage CLI.

The AppImage runtime's extraction fallback exceeded this machine's small tmpfs
in an early test, leaving a partial extraction. The working fallback uses a
private disk-backed directory. Upstream extraction caches can remain after
process exit; the test drivers clean only their own scratch directories. User
state, documents, receipts and screenshots are retained. FUSE avoids that
extraction overhead.

CFW was not modified; its existing **49 Python tests passed**. Existing container
and hosted contracts remain covered by Cage's regression suite. ARM hosted
Selkies/CFW support remains outside this AppImage milestone.

## Remaining limits

Both architectures require glibc **2.43 or newer**, X11/XWayland and either FUSE
or sufficient executable disk-backed scratch space. ARM qualifies 4 KB and
16 KB kernels only. AppImage export explicitly accepts ordinary user filesystem
and network access via `--allow-host-access`; it cannot enforce the recipe's
offline container/Flatpak policy.

Automatic application updates, state migration/rollback, MIME defaults, native
Wayland, broad audio/video/printing/IME/GPU support, CFW, arbitrary installers,
older glibc, ARM32 and macOS remain unqualified. Artifacts are unsigned local/CI
proofs; no public package or container release was performed. See
[usage and architecture](appimage-exports.md).
