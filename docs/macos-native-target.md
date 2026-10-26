# Minimal native macOS CLI target

The experimental `macos` target consumes the pinned MetalSharp-Wine v2.0
Darwin ARM64 runtime from the [runtime proof](macos-runtime-proof.md). It builds
and runs a sealed Cage bundle using ordinary user host access. `.app` packaging,
Finder integration, managed sandboxing, updates/migrations, CFW, installers,
i386 and GPU qualification are deferred.

Linux and Asahi retain their existing providers, images, recipes and launch
paths. Native selection is explicit: `wine-macos` version `11.20`, `winemac`
display, `host` build/runtime network, and `--target macos`. An ordinary native
Wine process cannot enforce Cage's Linux `network: none` contract; unsupported
requests are rejected rather than silently ignored. Build and run require
`--allow-host-access` to acknowledge this actual boundary.

## Build and run

On Apple Silicon macOS 15 or newer, with Python 3.11+ and Cage installed, prepare
the existing checksum-pinned x64 application source in a fresh checkout/staging
area, then build:

```sh
python scripts/prepare-flatpak-poc.py
python -m cage build recipes/notepadplusplus-portable-macos.cage.yaml \
  --target macos --allow-host-access --output dist/macos
python -m cage run dist/macos/notepadplusplus-portable-macos-8.8.8 \
  "$HOME/Documents/example.txt" --allow-host-access
```

The preparation helper refuses to overwrite existing source staging. Both
planning commands (`build --dry-run`, `run --dry-run`) are read-only: they do
not initialize state, acquire a runtime or create a bundle. Run planning still
requires a verified materialized bundle and host-access acknowledgement.

`--macos-store` selects a separate runtime cache; its default is
`~/Library/Caches/Cage/metalsharp-v2.0`. Build explicitly acquires missing
runtime inputs, verifies the publisher/source pins and archived bytes, extracts
the contained payload and checks native signatures/imports. The entire payload
is bound to the SHA-256 inventory digest observed in the successful runtime
proof. Cached changes fail closed; the cache is not overwritten or repaired
automatically. Launch never downloads or substitutes a runtime.

`--state-dir` selects the parent for per-application state; its default is
`~/Library/Application Support/Cage/macos`. Source prefixes remain sealed.
The existing lifecycle lock, initialization transaction, exact seed/runtime/
launch identity and generation record create a private writable prefix once.
Relaunches reuse it. Mismatched or incomplete state is retained and refused;
cross-platform prefix adoption and automatic migration are not implemented.
`run --state-action state-info` reports its recorded state. Natural Wine-server
shutdown is required; a failed or orphaned process cannot be made successful
by a forced kill in the native launcher.

The initial module set is `files`, `registry` and file `check`. Cage uses its
existing ordered operation plan, source audit/snapshot, registry compiler,
bundle/seed seals and state machinery. The native adapter executes the selected
operations using Python and the pinned Wine tools. It does not execute the
Linux shell commands recorded in the generic operation plan. Container exports
and other desktop formats cannot consume this Darwin target.

## CI acceptance

The macOS workflow builds the native recipe through `cage build`, verifies and
relocates the bundle, then runs it twice through `cage run`. A Windows test
driver attaches to the Cage-launched application instead of launching its own
copy. It verifies the recipe-created registry value, advances a registry launch
counter, edits/saves through the visible editor, checks persisted zoom on the
second launch and closes normally. The host independently checks exact saved
bytes, an unchanged state generation, natural shutdown, no remaining runtime
process and an unchanged source prefix. A deliberately modified cache file
must be refused before state changes or application launch. The original bytes
are restored only in the disposable CI cache after that negative test.

CI retains bundle verification, native operation order, provenance/signature
receipts, state identities, process snapshots, exact documents, screenshots and
failure logs. Runtime inputs are not republished. Archive/source identity and
ad-hoc signature integrity remain separate from reproducible source-to-binary
correspondence, Developer ID/notarization and redistribution clearance.

## apple/container assessment — 2026-10-25

[apple/container](https://github.com/apple/container) executes **Linux** OCI
images in lightweight VMs on Apple Silicon. Its supported host is currently
macOS 26. Its [technical overview](https://github.com/apple/container/blob/main/docs/technical-overview.md)
describes per-container VMs and selective host directory sharing; its
[command reference](https://github.com/apple/container/blob/main/docs/command-reference.md)
includes OCI build/run, mounts and Linux capability controls.

That is useful for a future Cage Linux OCI backend on macOS, including isolated
Linux build tools or a separately qualified Linux Wine/FEX workload. It does
not execute the Darwin Mach-O runtime or turn `winemac.drv` into a Linux display
driver, so it is not the confinement mechanism for this native target. Such a
backend would require an explicit adapter: Cage currently emits Docker/Podman
arguments and some managed workflows require local rootless Podman/crun.
File sharing, state durability, networking, display and device behavior would
need their own evidence. No Apple container service, dependency or Linux VM is
introduced by this native implementation.
