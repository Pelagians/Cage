# Native macOS runtime experiment

The original `macOS MetalSharp runtime proof` tested an exact upstream runtime
outside Cage's build/run/export adapters. That completed proof is recorded
below. The workflow now exercises the [minimal native CLI target](macos-native-target.md)
through build/run and persistence, with Linux/Asahi selection unchanged.

The lock, originally `tests/fixtures/macos-metalsharp-v2.0.json`, now lives in
`runtime/macos-metalsharp-v2.0.json` for the native provider. It binds the published
v2.0 relocatable ARM64 tar archive, its byte size and SHA-256, the publisher's
checksum manifest, the release/tag/source identities and Wine/FEX/graphics
source gitlinks. The proof retains pinned license files, release metadata, a
complete extracted inventory and a native core Mach-O/signature/import audit.
BSD-tar AppleDouble sidecars are identified by format, size and a contained
counterpart. Their hashes are retained without restoring publisher filesystem
xattrs; payload signatures are verified after extraction.
The archive's ad-hoc signatures are checked for integrity; this is not a
Developer ID/notarization assertion or a reproducible-build claim. In particular,
v2.0 predates the producer's WineForge attribution repair. This experiment does
not republish its runtime or establish redistribution clearance.

The first proof uses the unentitled relocatable runtime with 16-KiB host pages
on `macos-15`, `WINE_4K_PAGES=0`, software TSO enabled, full x87 precision and
disk cache/msync disabled. The full upstream runtime is kept intact. No runtime
source patches, signature changes, restricted entitlements, macOS privacy-policy
changes or Rosetta installation are applied.

An x64 Windows helper is built from `tests/probes/notepad_gui.c` in a separate
Linux job. It launches the same checksum-pinned Notepad++ 8.8.8 x64 portable
archive used by Asahi, finds the visible editor, verifies loaded text, edits
through Win32/Scintilla window messages and invokes Notepad++'s Save command.
It never writes the document or application settings itself. The macOS driver
independently verifies exact saved host-file bytes before permitting WM_CLOSE.
The second launch must load those bytes and the saved zoom setting, append text,
save again and close with exit code zero. This is programmatic Windows GUI
automation, not macOS keyboard/accessibility or Finder integration proof.

Both rounds use one fresh prefix. Natural `wineserver -w` completion and absence
of remaining runtime processes are required. No kill or deadline extension can
make a failed round pass. Forced cleanup only runs after a failure and is
explicitly recorded. Application seed and upstream runtime inventories must
remain unchanged. The experiment creates a new runner-temporary directory and
refuses to reuse an existing one; installed applications/state are not accessed.

The workflow retains evidence for failed gates as well as successes. Screenshots
are supplementary: their status is recorded, while visible-window and exact
content assertions come from the GUI probe and independent host checks. The
receipt's provenance status means verified publisher input identities, not
authenticated source-to-binary correspondence. Managed permissions, native
packaging/signing, updates, CFW, i386 and graphics acceleration remain separate.

Run the workflow by pushing a branch that changes its scoped files, opening a
pull request, or using workflow dispatch once the definition is on the default
branch. Each proof artifact contains `result.json`, provenance/signature/source
records, source and runtime inventories, GUI receipts, saved text, settings,
process snapshots and logs. A source-only test pass is not a macOS runtime pass.

## Observed proof — 2026-10-25

[Successful workflow 40261187561](https://github.com/Pelagians/Cage/actions/runs/40261187561)
tested implementation `9460998422d7412461448e1370aad585fa4edfa4` through PR merge
revision `3b35c2c1dc6365ee37c8d680fd21ed0f654a7cc7`. Later documentation-only
changes do not change those tested implementation bytes.

The Apple Silicon runner used macOS 15.7.9, build `24G830`, image
`20260907.0337.1`, with 16,384-byte host pages. Both visible Notepad++ sessions
passed initial-content checks, exact host-file saves and exit code zero. The
second process loaded the first save and zoom `3` from the same prefix, appended
text and saved again. Both natural Wine-server waits completed, process checks
found no remaining runtime process, and no forced cleanup occurred. Both
screenshots show the real macOS desktop and application window.

The runtime's recorded SHA-256, publisher/source pins and component notices were
verified. All 117 audited core Mach-O files passed architecture, signature and
import checks; all 7,936 extracted runtime inventory entries remained unchanged.
The application seed also remained unchanged. Separate source CI passed
681 tests and 255 subtests, with 40 skips. This establishes one unentitled
Darwin ARM64 runtime/x64 application case, not a full native Cage target,
source-to-binary reproducibility, restricted-entitlement or redistribution proof.

The workflow artifact retains the receipts, screenshots, inventories and logs
for 14 days. A local evidence copy is retained in ignored
`.cage/macos-proof-evidence/40261187561/`. The initial attempts found a GUI-driver
Unicode-definition error and unhandled BSD-tar AppleDouble metadata; both were
corrected in the proof harness before the successful run, without changing
MetalSharp's runtime bytes or weakening the runtime gates.
