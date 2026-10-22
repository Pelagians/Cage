# Trusted release qualification

Implementation source: `a3f710c`, following the existing Cage/CFW baseline at
`ba80078`. See [trusted releases](trusted-releases.md) for usage and scope.

## Source and native transport checks

Python 3.13 with the optional `cryptography` dependency: **571 tests and 194
subtests passed**. Evidence: `.cage/onboarding/trusted-full-tests.log`.
Tests cover real Ed25519 signatures, public CLI key generation/create/fetch,
wrong keys, tampered metadata and cached payloads, exact-package proof binding,
canonical cache/document path boundaries, redirects before contact, bounded
downloads, interrupted-download retry, hardlink/symlink partial protection, low space,
stale sequences after rollback, runtime/profile changes, interruptions before
and after commit, protected storage diagnostics, foreign Flatpak commits before
helper execution, and both Podman image-ID representations.

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

1. creates an ephemeral publisher identity outside the served/uploaded tree;
2. signs only package/image bytes bound by its completed ordinary qualification;
3. installs over loopback HTTP into private application/release state;
4. opens/saves a document and changes a real preference;
5. updates, relaunches through installed desktop integration where available,
   rolls back and relaunches again;
6. checks exact EXEs, preserved preferences, original host document bytes,
   retained old generations and the latest qualified prefix document;
7. confirms rollback keeps the accepted sequence high-water mark and cached
   inspection works after the server is stopped.

The completed runs establish ten trusted delivery cases, with five real
application sessions each. They cover all six requested format/architecture
targets through Notepad++. **SumatraPDF ARM64 desktop trusted delivery is not
qualified**, and the onboarding workflow remains red rather than suppressing
that failure:

| Application | Architecture | Flatpak | AppImage | OCI |
| --- | --- | --- | --- | --- |
| SumatraPDF 3.6 → 3.6.1 | x86_64 | Passed | Passed | Passed |
| SumatraPDF 3.6 → 3.6.1 | ARM64 | Failed shutdown twice | Not reached | Passed on retry |
| Notepad++ 8.8.8 → 8.8.9 | x86_64 | Passed | Passed | Passed |
| Notepad++ 8.8.8 → 8.8.9 | ARM64 | Passed | Passed | Passed |

Runs: [SumatraPDF onboarding and migration](https://github.com/Pelagians/Cage/actions/runs/39855691874),
[Notepad++ updates and delivery](https://github.com/Pelagians/Cage/actions/runs/39855691961).
The SumatraPDF ARM64 container job initially stopped on an upstream HTTPS
connection reset while downloading its pinned source, before application build or
execution. The container retry passed at the unchanged source.

Both ARM64 desktop attempts passed ordinary legacy migration, update and rollback
(six sessions). The first then timed out during trusted rollback; the second timed
out on the first trusted baseline launch. Each log recorded the save and final
window close, but the Wine process did not return within 120 seconds. The first
failure retained both signed releases, its sequence high-water mark of two and
its pending rollback journal. No forced shutdown/commit, longer timeout or relaxed
assertion has been added. AppImage qualification did not run after the Flatpak
failure and cannot be inferred from other targets.

The application's exit-code log precedes cleanup in the
[pinned upstream source](https://github.com/sumatrapdfreader/sumatrapdf/blob/3.6rel/src/SumatraStartup.cpp#L2602);
it is not an observed successful process return. This evidence does not establish
whether the root cause is application cleanup, Wine/FEX or their interaction.
The remaining acceptance criterion is a reproducible, normal-exit trusted
install/save/update/relaunch/rollback flow for **both** ARM64 desktop formats,
with the existing document/settings and committed-generation assertions intact.
Until then, do not advertise these two SumatraPDF targets as qualified trusted
releases. Existing ordinary proof results remain separately reported.

Failed desktop evidence:
[attempt 1](https://github.com/Pelagians/Cage/actions/runs/39855691874/artifacts/12461871132),
[attempt 2](https://github.com/Pelagians/Cage/actions/runs/39855691874/artifacts/12463198488).
Local retained records are
`.cage/onboarding/trusted-ci-failed-sumatra-arm-desktop{,-retry}` and corresponding
`trusted-sumatra-arm-desktop-a3-{job,retry-job}.log` files.

**20 detached Ed25519 signatures were independently verified.** The ten successful
records cover **50 application sessions** in CI. Record checks cover
proof/receipt hashes, exact package/image bindings, upstream EXE pins, saved host
document hashes, settings, rollback and the retained sequence high-water mark.
Package payload hashes are exercised by the actual CI consumer; large package
binaries are not downloaded again to this low-space host. Diagnostic extraction
uses bounded ZIP byte ranges and excludes package binaries and private keys.
Evidence: `.cage/onboarding/verified-trusted-evidence.json` and the
`trusted-ci-final-*` directories. Sample screenshots were checked for the saved
PDF and Notepad++ document after rollback/relaunch.

Independent [Flatpak](https://github.com/Pelagians/Cage/actions/runs/39855691649),
[AppImage](https://github.com/Pelagians/Cage/actions/runs/39855691672) and
[ARM64 Wine/FEX](https://github.com/Pelagians/Cage/actions/runs/39855691716)
regression workflows passed at the same source revision.

## Boundaries

The existing installed Notepad++ Flatpak/AppImage, documents, settings and prior
desktop recovery snapshots were not changed. Large new Wine/package builds were
not attempted on the nearly full Asahi host, and OSTree's free-space reserve was
not reduced. Final application CI uses 4 KiB kernels; the new trusted application
flow still needs its separate final 16 KiB hardware qualification.

No production publisher key or public binary release was created. Signature
trust is explicitly pinned by the user; qualification evidence is the publisher's
assertion rather than independent certification. Shared host/Flatpak platform
updates, revocation, online freshness and runtime/registry migration remain
outside this bounded implementation.
