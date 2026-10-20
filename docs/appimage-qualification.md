# AppImage qualification

The AppImage adapter is an experimental extension of the existing desktop
recipe/seed contract. Qualification is per package and workflow, not general
Wine or ARM compatibility.

The initial ARM candidate passed installed-menu launch, Unicode filename,
edit/save, close, relocated package relaunch, persisted zoom, second save,
unchanged package hash, and uninstall retaining state on Fedora Asahi's physical
Apple M1 with a 16 KB kernel. Both normal FUSE and disk-backed extraction
fallback were exercised. A small tmpfs extraction failed and was retained as a
failure case; fallback needs adequate scratch space.

Clean Ubuntu userland testing identified missing X11 locale/keyboard data;
the revised candidate includes those pinned data files. Its qualification and
the x86 CI proof are recorded below once completed. A consumer container checks
its userspace dependencies and real GUI application behavior, not a booted
Ubuntu machine or a new GPU driver.

Local working evidence lives under ignored `dist/appimage-evidence/`; package
export receipts are adjacent to `dist/*.AppImage`. The `Desktop AppImage proof`
workflow builds each architecture and runs save/relaunch with clean Ubuntu and
Fedora consumers that contain neither installed Wine nor Python. Existing
Flatpak and ARM container workflows remain separate regression gates.

Public release, automatic updates/state migration, CFW, arbitrary Windows
installers, broad graphics/device support, older glibc and ARM32 remain outside
this milestone. Artifacts are unsigned local/CI proofs; no public package or
container release is performed. See [usage and architecture](appimage-exports.md).
