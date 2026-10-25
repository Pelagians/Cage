# Runtime migration qualification

Implementation source: `85fc1881b3c085b452350bb76d990254e08eaa10`.
Date: 2026-10-23. Usage and compatibility policy:
[safe runtime migrations](runtime-migrations.md).

## Routine ARM repaired rollback

Automatic ARM qualification now uses the existing explicit repaired-rollback
operation and the identified `fex-2610-cage1` runtime. It restores original
settings and current documents into a fresh guarded generation, retains the
original prefix and package unchanged, and requires actual zero exit, Wine
quiescence and a committed generation before recording success. x86_64 automatic
qualification retains exact runtime migration and rollback.

Manual `rollback_repair=false` runs retain exact original-runtime diagnostics.
The original ARM runtime and its failed trials remain unqualified; a guarded
repair is not a repair of those immutable bytes. Repair proofs sign/fetch only
the repaired target. Full trusted repair deployment still requires independent
matching original-package qualification as described in the usage document.

Idle-lock timeout collection also records the lock error and finds detached
processes holding that private proof's exact lock inode. Menu-launcher exit zero
cannot suppress a live lease or turn a failed shutdown into a passing trial.
The 120-second process deadline and 60-second quiescence deadline are unchanged.

## Final CI result on 2026-10-23

All six workflows completed successfully at source
`270e1879472a7cf575ffc3da016c80f666407029`:

| Workflow | Result |
| --- | --- |
| [Runtime migration and rollback](https://github.com/Pelagians/Cage/actions/runs/40000471514) | All four cells passed |
| [Application onboarding and legacy migration](https://github.com/Pelagians/Cage/actions/runs/40000471490) | All four cells passed |
| [Application update and rollback](https://github.com/Pelagians/Cage/actions/runs/40000471613) | All four cells passed |
| [Flatpak](https://github.com/Pelagians/Cage/actions/runs/40000471516) | Passed |
| [AppImage](https://github.com/Pelagians/Cage/actions/runs/40000471444) | Both architectures passed |
| [ARM Wine/FEX](https://github.com/Pelagians/Cage/actions/runs/40000471519) | Passed |

The final runtime matrix independently verified **14 cases, 70 GUI sessions and
12 Ed25519 signatures**, including different actual ARM translator and x86_64
7-Zip payload hashes. Evidence records are in
`.cage/asahi-installed-qualification/runtime-migration-ci-270e187/`;
`verify-runtime-migrations-270e187.py` and
`verified-runtime-migrations-270e187.json` are in its parent qualification folder.
The separate stress proof below adds **105 sessions and four signatures**. These
are software CI proofs on 4 KiB kernels, not new installed Asahi/16 KiB migration
qualification. Package/image bindings were verified through signed receipts and
CI records; consumer binaries were not downloaded and independently rehashed.

A final rehash confirmed all **25,112 original protected entries** and the normal
installed Flatpak commit unchanged. Evidence:
`runtime-migration-ci-followup-user-state-final.json` and its `.log` counterpart.
No normal application installation was upgraded and no user recovery data was
pruned. The metadata-only native test never started its temporary container.

Changes in this follow-up concern CI evidence collection and optional bounded
stress. No production Wine payload or generation transaction was changed.
Earlier failed attempts remain recorded below. Passing reruns and stress tests
do not establish the causes of their intermittent shutdown failures, which are
still unconfirmed. No application failure was converted into a passing trial.

## CI follow-up investigation on 2026-10-23

At source `4b6b88c33f3b287be126a04d6c0726d324ef31d9`, all five regression
workflows passed: [onboarding](https://github.com/Pelagians/Cage/actions/runs/39933053958),
[application updates and rollback](https://github.com/Pelagians/Cage/actions/runs/39933053996),
[Flatpak](https://github.com/Pelagians/Cage/actions/runs/39933054145),
[AppImage](https://github.com/Pelagians/Cage/actions/runs/39933054082), and
[ARM Wine/FEX](https://github.com/Pelagians/Cage/actions/runs/39933053961).

The repeated [runtime migration matrix](https://github.com/Pelagians/Cage/actions/runs/39933054117)
passed both desktop cells and x86_64 containers but failed the final trusted ARM
OCI relaunch after rollback. The application logged exit code zero and its GUI
closed; the launcher still waited for Podman at the 120-second deadline. This
alone does not establish whether Wine cleanup or the container client hung.
The restored baseline uses the original, unrepaired FEX payload. No failed trial
is counted as passed, and no signing/qualification gate or timeout was relaxed.

The later [source-65 ARM desktop cell](https://github.com/Pelagians/Cage/actions/runs/39994050603/job/120552853060)
also timed out on the first trusted AppImage baseline session, before migration.
Its retained snapshot shows a single Sumatra thread waiting on a futex after the
application logged exit zero. This again used the unrepaired baseline translator;
it is not evidence of a candidate-runtime failure. The snapshot does not establish
the exact lock owner or cause. AppImage consumer diagnostics did not include a
native debugger stack. Records are retained under
`runtime-migration-arm-desktop-failure-65b693c/trusted-appimage/`.

The failure exposed a diagnostic defect: Podman's volume filter matches a volume
name or container mount destination, not the host bind-mount source. The probe
now filters `/var/lib/cage/state`, then verifies the exact unique host source
before collecting container state and host PIDs. It includes stopped containers
and uses debugger attach/detach for the owned application or direct child client.
No diagnostic signal is sent through Podman's default signal proxy.
See the [Podman filter documentation](https://docs.podman.io/en/latest/markdown/podman-ps.1.html#filter-f-filter).
The corrected selection also passed a native Asahi/16 KiB metadata test with one
never-started read-only temporary container. It launched no Wine/application,
changed no image tags, and removed only that container afterward.

The final diagnostic source is
`270e1879472a7cf575ffc3da016c80f666407029`. Its full local suite passed
**608 tests and 214 subtests**. Fresh protected-state verification again confirms
all **25,112 original entries** and the normal installed Flatpak commit unchanged.
Evidence is under `.cage/asahi-installed-qualification/`:
`runtime-migration-ci-fix-unit-tests.log`,
`runtime-migration-ci-followup-user-state-check.json`, and
`container-diagnostic-filter/result.json`. All final-source reruns passed as
recorded above; the underlying intermittent shutdown timeout is not claimed fixed.

The [bounded container stress run](https://github.com/Pelagians/Cage/actions/runs/39996341350)
at `61b6d8fa33c74ca73a56a6a4dd58c24004edaa36` passed **105 GUI sessions**:
90 ARM sessions across direct container, OCI and trusted OCI, plus 15 x86_64
sessions. This includes **75 extra ARM save/close/relaunch cycles** against the
exact retained rollback runtime. All saved hashes, preferences, directed runtime
identities and four retained Ed25519 signatures were independently verified in
`verified-runtime-migration-stress-61b6d8f.json`. A failed cycle immediately fails
the proof; the mode does not retry failures. Its optional manual input is
`container_stress_relaunches=25`; default `0` leaves the normal four-cell matrix
and five-session proof unchanged. The stress-only run intentionally omits desktop
cells and does not replace their qualification.

A separate [older ARM onboarding cell](https://github.com/Pelagians/Cage/actions/runs/39994050734/job/120552854628)
failed its first legacy-v0 session with exit 247 after the application logged
exit zero. This uses the repaired FEX runtime with the sealed historical helper,
so it cannot simply be attributed to the original unrepaired translator. Its
actual cause is unestablished, including any possible memory-related kill.
The retained record is `onboarding-arm-failure-65b693c/container/1-original.log`.
Final diagnostics capture bounded kernel output and cgroup memory-event records
on nonzero exits as well as timeouts, only in the ephemeral CI job. They preserve
the original failure and never reinterpret a nonzero exit as success. Passing
stress and retries do not establish that this separate legacy issue is fixed.

## Initial qualification

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
and its
[diagnostics follow-up](https://github.com/Pelagians/Cage/actions/runs/39933053958)
both passed. Their ARM64 desktop cells completed successfully.

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
shutdown fix. The other cells of that broader follow-up subsequently passed.

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
