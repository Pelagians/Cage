# Minimal native macOS target and local app

The experimental `macos` target consumes the pinned MetalSharp-Wine v2.0
Darwin ARM64 runtime from the [runtime proof](macos-runtime-proof.md). It builds
and runs a sealed Cage bundle using ordinary user host access. A minimal local
`.app` export opens the same bundle through LaunchServices. Managed sandboxing, updates/migrations, CFW, installers,
i386 and GPU qualification are deferred.

Linux and Asahi retain their existing providers, images, recipes and launch
paths. Native selection is explicit: `wine-macos` version `11.20`, `winemac`
display, `host` build/runtime network, and `--target macos`. An ordinary native
Wine process cannot enforce Cage's Linux `network: none` contract; unsupported
requests are rejected rather than silently ignored. Build and run require
`--allow-host-access` to acknowledge this actual boundary.

## Build and run

On Apple Silicon macOS 15 or newer, with Python 3.11+, Xcode Command Line Tools
(for the native binary audit) and Cage installed, prepare
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

## Local .app export

After building the native bundle and retaining its verified Wine cache:

```sh
python -m cage export macos-app dist/macos/notepadplusplus-portable-macos-8.8.8 \
  --allow-host-access --output "$HOME/Applications/Notepad Cage.app"
open -a "$HOME/Applications/Notepad Cage.app" "$HOME/Documents/example.txt"
```

The output must be new; existing applications are retained. `--dry-run` verifies
the source and prints a plan without downloading or creating state or a package.
The exporter needs the same native build tools as the CLI target. It includes
the sealed bundle, a native AppKit host, a Cage source snapshot and checksum-pinned
[CPython 3.13.16 from python-build-standalone 20261013](https://github.com/astral-sh/python-build-standalone/releases/tag/20261013).
It reuses the AppImage exporter's bounded Python extraction checks, retains
Python's shipped license notices, and records the publisher tag/commit/asset
identities. Launch requires neither a checkout nor host Cage/Python/site packages.

Wine is **not embedded**: the app verifies the same previously acquired cache,
without downloading or repairing it. Default runtime and state paths resolve
under the launching user's home. Export options `--macos-store` and `--state-dir`
bind explicit paths when needed, including the disposable CI paths. These custom
paths remain external dependencies after moving the app. The `.app` keeps the
original native launch contract, application ID and exact state identity, so it
reuses CLI-created settings, registry data and documents without migration.

The host uses Apple's [bundle layout](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle)
and receives initial document-open events through
[AppKit](https://developer.apple.com/documentation/appkit/nsapplicationdelegate/application%28_%3Aopenfile%3A%29?language=objc).
Document declarations come from the recipe; export does not select a default
document handler. Initial document delivery and relaunch are supported. Opening
another document through Finder while a session is running is refused visibly;
use the application's Open command or close its window first. The host refuses
to terminate an active session forcibly. It exits after Cage's natural shutdown.
Launch failures are visible and logged at `~/Library/Logs/Cage/<application-id>/app-launch.log`.

The exporter signs the local app ad hoc and verifies its complete resource seal
before executing private Python. `Contents/MacOS/CageLauncher --cage-verify`
checks that seal without launching Wine or touching state. Python uses isolated
mode with bytecode writes disabled; mutable files remain outside the app. This
is a local packaging proof, not Developer ID signing, notarization, Gatekeeper
download qualification, a sandbox or redistribution clearance. The MetalSharp
source-to-binary and attribution holds in the original proof remain unchanged.

## CI acceptance

The macOS workflow builds the native recipe through `cage build`, verifies and
relocates the bundle, then runs it twice through `cage run`. A Windows test
driver attaches to the Cage-launched application instead of launching its own
copy. It verifies the recipe-created registry value, advances a registry launch
counter, edits/saves through the visible editor, checks persisted zoom on the
second launch and closes normally. Two further launches open a relocated `.app`
through LaunchServices, then move it again and verify that it reuses the same
CLI-created state and document. The host independently checks exact saved
bytes, an unchanged state generation, natural shutdown, no remaining runtime
process and an unchanged source prefix and app package. Changed app resources
must fail the native host's signature gate. A deliberately modified cache file
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
