# Reference Study

WinForge borrows from nearby systems without inheriting their wrong assumptions.

- Steam Runtime / pressure-vessel: execution envelope separation.
- UMU Launcher: Proton-style runtime selection outside Steam.
- umu-protonfixes: per-application fixups and Winetricks verbs, made declarative and auditable.
- Bottles: prefix lifecycle language, not GUI-first mutable bottle management.
- Lutris: declarative install ordering and runner configuration, not game-only mutable output.
- PlayOnLinux: Wine app scriptability, not undocumented scripts as the primary contract.
- wine-tkg-style tooling: pinned Wine/Proton runtime builds and provenance.
- ramalama: application-first UX and provider/driver selection pattern, applied to Wine-family runtimes.
- OCI images: canonical deployable artifact direction, not the user-facing semantic model by itself.
- docker-wine: mature Wine-in-container ergonomics (UID/GID mapping, X11/Xvfb/RDP/audio, entrypoint validation), but its goal is a general mutable Wine desktop/container rather than reproducible application artifacts.
- LSW: useful foundation-first compatibility architecture and path/registry translation reference, but its goal is direct PE/Win32 execution without Wine, including kernel/module work, which is outside WinForge's scope.
- Nix: reproducible inputs and immutable outputs.

Summary:

```text
application recipe -> resolved build -> sealed application artifact -> OCI deployable image -> run with separate runtime state
```
