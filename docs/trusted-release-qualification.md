# Trusted release qualification

Qualified implementation source: `cb45cba9da2814e292e99abe0130d15e45a34c65`.
The ARM64EC shutdown repair is `156263e`; `cb45cba` also preserves the exact
previous runtime pin for existing sealed native bundles. Trusted delivery builds
on `a3f710c` and the existing Cage/CFW baseline at `ba80078`. See
[trusted releases](trusted-releases.md) for usage and scope.

## Source and native transport checks

Python 3.13 with the optional `cryptography` dependency: **575 tests and 194
subtests passed**. Evidence: `.cage/onboarding/fex-compat-full-tests.log`.
Tests cover real Ed25519 signatures, public CLI key generation/create/fetch,
wrong keys, tampered metadata and cached payloads, exact-package proof binding,
canonical cache/document path boundaries, redirects before contact, bounded
downloads, interrupted-download retry, hardlink/symlink partial protection, low space,
stale sequences after rollback, runtime/profile changes, interruptions before
and after commit, protected storage diagnostics, foreign Flatpak commits before
helper execution, and both Podman image-ID representations. Additional tests
verify the actual pinned FEX DLL replacement, preservation of the original RPM
hardlink, refusal of altered source/DLL bytes, and read-only compatibility with
the exact previous runtime target. New builds still require the patched target;
unknown/mixed targets and cross-runtime prefix migration remain refused.

The bundled DLL rebuilt byte-for-byte from pinned source and compiler on Asahi
and in the [native ARM64 CI proof](https://github.com/Pelagians/Cage/actions/runs/39877572820).
The final wheel includes the DLL, provenance, notices, source patch and legacy
runtime lock. An existing sealed Notepad++ ARM bundle and its original immutable
carrier were verified and launch-planned without executing it or touching state.
Evidence: `.cage/onboarding/fex-wheel-check.json` and
`.cage/onboarding/fex-legacy-native-check.json`.

An actual **native OCI transport check passed on Asahi ARM64 / 16 KiB pages**.
It built a tiny disposable scratch image, inspected metadata without executing
its nonexistent entrypoint, saved/hashed/signed the archive, verified and loaded
it, checked immutable metadata, and recorded/read its installation. The test
found and fixed bare-vs-prefixed Podman JSON image IDs. Its image tags and
private key were removed after the check.

This was a **synthetic metadata/transport fixture, not a Wine or Windows
application proof**. Evidence:
`.cage/onboarding/trusted-native-oci-transport.{json,log}` and the local test
script alongside those files.

## Native application delivery matrix

The onboarding and update workflows now run the existing ordinary application
proofs, then reuse those exact qualified packages through trusted delivery.
The matrix targets both pinned applications through native x86_64/ARM64 Flatpak,
clean-consumer AppImage and persistent OCI delivery. Each trusted proof must:

1. create an ephemeral publisher identity outside the served/uploaded tree;
2. sign only package/image bytes bound by its completed ordinary qualification;
3. install over loopback HTTP into private application/release state;
4. open/save a document and change a real preference;
5. update, relaunch through installed desktop integration where available,
   roll back and relaunch again;
6. check exact EXEs, preserved preferences, original host document bytes,
   retained old generations and the latest qualified prefix document;
7. confirm rollback keeps the accepted sequence high-water mark and cached
   inspection works after the server is stopped.

Both pinned applications passed ordinary and trusted **Flatpak and AppImage**
qualification on x86_64 and ARM64. Each Sumatra desktop case includes six
ordinary sessions (including supported legacy adoption), then five trusted
sessions using the same package bytes. Successful closure requires the actual
launcher process to return zero and the lifecycle lock to become idle before
checking committed state. No forced-success path, longer shutdown timeout or
relaxed data assertion was introduced.

| Application | Architecture | Flatpak | AppImage | OCI |
| --- | --- | --- | --- | --- |
| SumatraPDF 3.6 → 3.6.1 | x86_64 | Passed | Passed | Passed |
| SumatraPDF 3.6 → 3.6.1 | ARM64 | Passed | Passed | Passed on retry |
| Notepad++ 8.8.8 → 8.8.9 | x86_64 | Passed | Passed | Passed |
| Notepad++ 8.8.8 → 8.8.9 | ARM64 | Passed | Passed | Passed |

Runs: [SumatraPDF onboarding and migration](https://github.com/Pelagians/Cage/actions/runs/39877572837),
[Notepad++ updates and delivery](https://github.com/Pelagians/Cage/actions/runs/39877572840).
Independent [Flatpak](https://github.com/Pelagians/Cage/actions/runs/39877572930),
[AppImage](https://github.com/Pelagians/Cage/actions/runs/39877572892) and
[ARM64 Wine/FEX](https://github.com/Pelagians/Cage/actions/runs/39877572820)
regression workflows passed at the same source revision.

**24 detached Ed25519 signatures were independently verified** across twelve
successful trusted records / **60 application sessions**. Checks cover the exact
source revision and current ARM runtime target, proof/receipt hashes, package or
image identity, upstream EXE pins, saved document hashes, settings, rollback and
the accepted sequence high-water mark of two. Payload hashes were exercised by
the actual CI consumer; large packages were not downloaded again to the low-space
host. Bounded ZIP range extraction excluded package binaries and private keys.
Evidence: `.cage/onboarding/verified-trusted-evidence.json` and the
`shutdown-cb45-*` directories.

The ordinary ARM64 Sumatra AppImage rollback screenshot and trusted ARM64 Flatpak
rollback screenshot show the saved PDF rendered. The trusted ARM64 AppImage root
screenshots are blank and provide no visual rendering evidence; that case is
supported by the real window/title/Save As interactions, exact saved bytes,
preference and generation checks, normal process returns and menu relaunches.
The ordinary AppImage proof renders the same qualified package before trusted
delivery. Screenshot capture is a remaining evidence limitation.

## Shutdown repair and retained failures

The prior desktop holds are superseded by these completed proofs, with their
failed evidence retained:
[attempt 1](https://github.com/Pelagians/Cage/actions/runs/39855691874/artifacts/12461871132),
[attempt 2](https://github.com/Pelagians/Cage/actions/runs/39855691874/artifacts/12463198488).
The failure was reproduced on Asahi: after peer termination, the sole remaining
thread waited for a FEX lookup-cache writer that no longer existed. The shared
ARM64EC termination callback now drains translator locks before Wine kills peer
threads. See the [shutdown analysis and reproducible repair](arm64-shutdown.md)
for the symbolized stack, pinned source/build identity and state boundaries.

With the final DLL, **25 consecutive private Asahi M1 / 16 KiB save, preference
change and normal-close sessions passed**. Shutdown took 0.243–0.752 seconds
(median 0.548 seconds), saved bytes were preserved and originals were unchanged.
This used a loose AppDir inside the pinned SDK build sandbox with private state;
it does not establish a full installed Flatpak/AppImage update-and-rollback
hardware proof. Evidence: `.cage/shutdown-asahi/final-stress-summary.json` and
`final-stress-results.json`.

A separate ordinary ARM64 OCI attempt at `cb45cba` returned **247** after its
second save/close, rather than hanging. It remained failed, with its state and
logs retained. The available evidence does not distinguish a positive application
status from a propagated signal, and does not establish OOM or the shutdown-cache
bug as its cause. Two scoped diagnostic repetitions each passed all 17 native,
ordinary OCI and trusted OCI sessions; all six ordinary OCI containers in each
reported exit zero and `OOMKilled=false`. Those flags do not rule out a host-level
OOM. The diagnostic helpers differ from production and are excluded from the
normal signed qualification count. The original unmodified job then passed all
17 sessions on retry, including supported migration, trusted install/update and
rollback. Its successful signed records are included in the twelve-case count;
the earlier failure is not reclassified as success. Status 247 remains an
unexplained intermittent failure, separate from the diagnosed shutdown deadlock.
The temporary diagnostic workflow was removed after collecting these records.
Records: `.cage/onboarding/shutdown-cb45-arm-container`,
`shutdown-cb45-sumatra-arm-container-retry`,
`shutdown-scoped-oci-diagnosis{,-repeat}`,
[normal retry](https://github.com/Pelagians/Cage/actions/runs/39877572837/job/120187179857) and
[scoped diagnostic attempts](https://github.com/Pelagians/Cage/actions/runs/39879625302).

## Boundaries

The existing installed Notepad++ Flatpak/AppImage, documents, settings and prior
desktop recovery snapshots were not changed. Large new Wine/package builds were
not attempted on the nearly full Asahi host, and OSTree's free-space reserve was
not reduced. Final application CI uses 4 KiB kernels; the 25-session Asahi shutdown
stress proof is separate from full installed-package 16 KiB hardware qualification.
Existing packages and rollback generations retain their original runtime; this
repair does not authorize in-place runtime migration or manually replacing a DLL
inside a user's prefix.

No production publisher key or public binary release was created. Signature
trust is explicitly pinned by the user; qualification evidence is the publisher's
assertion rather than independent certification. Shared host/Flatpak platform
updates, revocation, online freshness and runtime/registry migration remain
outside this bounded implementation.
