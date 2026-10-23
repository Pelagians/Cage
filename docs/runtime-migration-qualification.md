# Runtime migration qualification

Implementation source: `85fc1881b3c085b452350bb76d990254e08eaa10`.
Date: 2026-10-23. Usage and compatibility policy:
[safe runtime migrations](runtime-migrations.md).

## Current result

The [runtime migration matrix](https://github.com/Pelagians/Cage/actions/runs/39925674407)
passed all four cells. The completed records independently verify **14 cases,
70 GUI sessions and 12 Ed25519 release signatures**, covering every environment
below. CI-only diagnostics changes in `4b6b88c33f3b287be126a04d6c0726d324ef31d9`
do not change this qualified runtime implementation.

| Environment | Cases | Status |
| --- | --- | --- |
| x86_64 Flatpak and AppImage, ordinary and trusted delivery | 4 | Passed |
| ARM64 Flatpak and AppImage, ordinary and trusted delivery | 4 | Passed |
| x86_64 direct container, OCI and trusted OCI | 3 | Passed |
| ARM64 direct container, OCI and trusted OCI | 3 | Passed |

These tests use pinned SumatraPDF 3.6 on both sides of each transition. The
application executable stays at
`c5d24aa361bdd9945d529e461bc4ad0bb4a28f3fff493be6f915c6d93f9b16b0`.
Runtime-only migration deliberately does not combine an application upgrade.
Desktop x86_64 changes Wine 11.0's packaged 7-Zip dependency revision; container
x86_64 changes WineHQ 10.0 to 11.0. ARM64 changes the original Wine 11.20/FEX
payload to the repaired termination-guard payload. Desktop records require
different actual dependency/translator hashes, not merely different identifiers.

Each case opens and saves a real PDF, changes a preference, migrates to the new
runtime, saves and relaunches, rolls back, then saves and relaunches again. Records
check unchanged executable pins, preferences, saved bytes, latest in-prefix
documents, retained generations and exact directed migration identities. Desktop
cases include menu launches. Trusted cases additionally check retained signed
releases and sequence high-water mark 2 after rollback.

Local evidence is under
`.cage/asahi-installed-qualification/runtime-migration-ci-85fc188/`.
The independent verifier is `verify-runtime-migrations-85fc188.py` in that
qualification folder; its summary is `verified-runtime-migrations-85fc188.json`. Verification covers CI-reported package/image hashes,
signed receipts and proof bindings. Consumer binaries were not downloaded and
independently rehashed locally.

## Regression and preservation checks

The complete local suite passed **604 tests and 214 subtests**. It covers
unlisted/foreign transitions, application/version/executable mismatch, ABI and
data-policy changes, nonzero trials, interrupted commits, insufficient storage,
unsafe links, runtime rollback, custom DPI, signed-history recovery and carrier
retention. The producer recipe helper is exercised through its real CLI, and
the existing shell builder through a fake engine with observable image state.
The state-manager subprocess tests use a fake Wine executable; they do not claim
real application compatibility.

The final-source [Flatpak regression](https://github.com/Pelagians/Cage/actions/runs/39925674309)
and [AppImage regression](https://github.com/Pelagians/Cage/actions/runs/39925674325)
passed. The [ARM Wine/FEX regression](https://github.com/Pelagians/Cage/actions/runs/39925674478)
passed an unchanged retry after its first pinned RPM download timed out before
application testing. Its original failure log is retained locally. The separate
[onboarding regression](https://github.com/Pelagians/Cage/actions/runs/39925674509)
was still running at this snapshot; the
[diagnostics follow-up](https://github.com/Pelagians/Cage/actions/runs/39933053958)
was pending. Neither is claimed as passed here.

A separate [ordinary Notepad++ update regression](https://github.com/Pelagians/Cage/actions/runs/39917829887)
hit a timeout waiting for the first trusted ARM OCI session to exit. Its raw
uploader also followed a Wine `Z:` link and lost the failure artifact. This does
not invalidate the completed SumatraPDF runtime-migration records. The
[follow-up ARM cell](https://github.com/Pelagians/Cage/actions/runs/39933053996/job/120345799241)
passed direct container, OCI and trusted OCI update/rollback with the original
120-second shutdown deadline and assertions. The retained three proof records
and two Ed25519 signatures were independently verified; see
`verified-notepad-regression-4b6b88c.json` in the local qualification folder.
The original timeout's cause is still unknown; this strict retry is not a runtime
shutdown fix. Other cells of that broader follow-up were still queued.

The shared safe collector now retains evidence without following Wine links or
uploading state/documents. App-specific shutdown diagnostics inspect only the
failed proof's descendants or a container with its exact private state mount.
No application timeout or shutdown assertion was relaxed.

All **25,112 previously protected entries** retain their original contents,
modes and literal symlink targets, and the normally installed Flatpak commit is
unchanged. Protection covers existing Notepad++ data, installed AppImage state
and packages, launchers and desktop recovery data. No normal installation was
upgraded. Evidence: `runtime-migration-user-state-check.json` in the same local
qualification folder. The three private proof roots listed there are from the
earlier installed qualification, not newly created by these implementation tests.

## Failures found and fixed

- The proposal CLI originally passed a string to a manifest loader requiring a
  `Path`. The actual CLI regression now covers that boundary.
- Historical runtime preparation hit pinned RPM transport timeouts. The dedicated
  matrix retries only bounded transport failures, retaining exact SHA checks.
  Application trials, GUI timeouts and shutdown failures are not retried or
  reinterpreted as successful.
- Rebuilding an ARM runtime moved its normal build tag and made the old
  `repository@digest` unavailable. The Python and shell builders now share
  same-repository retention before replacement and refuse failed/foreign
  retention. Native Podman reproduced the lost lookup without retention and
  verified it survives with retention. Temporary test tags were removed;
  original image tags, IDs and digests stayed unchanged. No layers or application
  processes were created by this native metadata check.
- A fresh runtime seed could lose a custom Wine DPI value in `preserve` mode.
  Only that supported display value is reapplied through the new runtime's
  `reg.exe`; registry hives and old system files are not copied.

Original failed attempts are retained separately from successful proof records.
The earlier `208310a` matrix passed both desktop cells and x86_64 containers;
its ARM container failure before baseline launch exposed the carrier issue.
Those records independently verified 11 cases, 55 sessions and ten signatures,
and are not substituted for final-source acceptance.

## Boundaries

CI runs on Linux x86_64/ARM64 with **4 KiB kernel pages** and private,
software-rendered X11 displays. AppImage runs in a clean Fedora consumer without
host Wine, using extraction mode. This is distinct from the previous installed
Asahi/FUSE qualification and its 48 sessions. The new runtime transitions have
not been exercised through installed GUI applications on Asahi/16 KiB pages.
The native Podman retention check on that machine qualifies metadata behavior
only. Existing installed settings, documents and rollback data remain untouched.

Only explicit qualified application/runtime pairs are supported. Other apps,
registry-dependent state, external runners and prepared CFW runtime transitions
need their own qualification; existing CFW and hosted workflows are unchanged.
No production publisher key or public binary release was created.

XWayland remains the default. Native Wine Wayland with Wine 11 and newer is an
explicit future backend qualification, including its driver/dependencies,
compositor access, scaling, clipboard, file handling and rollback. These X11
proofs do not claim native Wayland or physical GPU acceptance.
