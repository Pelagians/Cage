# ARM64EC shutdown guard

The shared ARM runtime includes `fex-2610-cage1`, a small source patch to FEX
2610's ARM64EC termination callback. Flatpak, AppImage and native containers
consume the same checked DLL. Wine, the FEX WoW64 module, application archives,
CFW and the x86_64 runtime retain their existing implementations.

## Failure and repair

SumatraPDF sometimes saved its document and settings, closed its last window,
and logged exit code zero, while its Wine process remained alive. The application
log precedes cleanup and cannot establish successful termination. The proof
continues to require an actual process return of zero before committing an update
or rollback generation.

This reproduced on the Asahi M1 / 16 KiB host on the fourteenth repeated private
save/close session. Read-only native register, syscall-context and stack captures,
symbolized with the packaged PE symbols, identified this path:

```
RtlExitUserProcess -> LdrShutdownProcess -> RtlProcessFlsData
  -> application cleanup callback -> FEX CompileBlock -> LookupCache::FindBlock
  -> WritePriorityMutex::lock_shared -> RtlWaitOnAddress
```

Only the main application thread remained. The lookup-cache mutex retained
`WRITE_OWNED_BIT | READ_WAITER_BIT` (`0xc0000000`); the writer could no longer
release it. In the pinned
[Wine wrapper](https://github.com/wine-mirror/wine/blob/wine-11.20/dlls/ntdll/signal_arm64ec.c),
`ProcessTerm` brackets `NtTerminateProcess(NULL)`, which terminates peer threads
while allowing the caller to continue process cleanup. The pinned
[FEX callback](https://github.com/FEX-Emu/FEX/blob/FEX-2610/Source/Windows/ARM64EC/Module.cpp)
was empty. A peer could therefore disappear while writing the shared code cache;
final cleanup could subsequently need another translated callback.

The patch takes `ThreadCreationMutex`, then the existing exclusive code
invalidation mutex, before peer termination. This drains compilation and cache
writers in the existing notification lock order. It releases both locks in
reverse order after the syscall, including an unsuccessful syscall. An absent
context during early startup is left alone. It changes neither application exit
codes nor Cage's lifecycle/commit policy.

The independent AppImage consumer also exposed an X11 transport error: a display
advertising SysV MIT-SHM was shared across different IPC namespaces. Its test
display, and the external-display container proof, now disable that extension.
This preserves private IPC namespaces and exercises X11's image-transfer fallback;
it does not qualify cross-namespace MIT-SHM or add host IPC privileges. Flatpak
retains its existing explicit IPC permission.

## Pinned bytes and reproduction

`runtime/vendor/fex-2610-cage1/source.json` records the exact FEX commit,
compiler checksum, all seven unchanged provider patches, source patch checksum,
build epoch and DLL checksums. Required submodule commits are pinned by the FEX
tree. The bundled compressed DLL adds about 882 KiB to the source distribution;
installed applications need no compiler, git, cmake or additional service.

On native Linux ARM64, with Python, git, cmake and ninja:

```sh
python scripts/rebuild-fex-shutdown.py --work /tmp/cage-fex-rebuild --jobs 2
```

The work directory must be new. The script retains its build for inspection and
fails if the rebuilt DLL differs byte-for-byte from the bundled DLL. It downloads
the pinned compiler and sources, so allow space for them. The native ARM CI runs
this check before its application proofs.

The final uncompressed DLL SHA-256 is
`8e84d8deb007e6951e10696d9fe19e8dc7ca6044406220effd7503d4ab218b6a`.
`runtime/arm64ec.py` verifies the source identity, compressed bytes, bounded
decompression, DLL bytes and original RPM DLL before replacing that one file
atomically. Replacement preserves any other RPM hardlink's original contents.
Notices, source identity and the patch accompany the runtime payload.

The runtime lock separately records the original RPM inventory and the resulting
patched inventory. Existing build caches are retained; a patched cache receives
its own payload/receipt names. Container installation applies the same verified
replacement after normal RPM dependency resolution.

## State and qualification boundaries

The runtime target has a new identity. Previously exported packages, installed
apps, settings, documents and rollback packages are not rewritten. Cage retains
the previous exact runtime pin for verifying and launching existing sealed native
ARM bundles with their original immutable carrier image. New builds require the
patched pin; unknown or mixed targets remain rejected. Existing
cross-runtime migration checks remain in force: attempting an ordinary update
from an older runtime target is refused with all state retained. This patch does
not qualify an in-place runtime migration or justify manually replacing a DLL in
a user's Wine prefix.

The qualification uses fresh private application state and exact pinned Sumatra
3.6/3.6.1 packages, with unchanged legacy adoption, update, save/relaunch, rollback
and trusted delivery assertions. Results and exact CI runs are recorded in the
[trusted release qualification report](trusted-release-qualification.md).
Loose AppDir stress sessions on Asahi establish a separate 16 KiB shutdown check;
they do not replace full installed-package qualification.

The [original OCI diagnosis and recovery](shutdown-investigation.md#original-oci-diagnosis-2026-10-23)
also confirms this lock path in native Asahi OCI and 4 KiB CI captures. Recovery
of the actually failed private prefix through an explicit `cage1` runtime
migration passed 104 normal sessions, including original-runtime rollback and
guarded re-upgrade, with settings, documents and four generations retained.
The original runtime's failed trials remain failed under the strict gate.
