# Application onboarding qualification

Qualified sources: SumatraPDF portable x64 **3.6 / 3.6.1**, pinned in
`recipes/sumatrapdf-portable.releases.json`. See the shared recipe and supported
boundaries in [application onboarding](application-onboarding.md).

## Source checks

Python 3.13: **548 tests and 192 subtests passed**, including isolated wheel
construction. Unchanged CFW at `18216a01876c509143b86f857fed3f5f72871257`:
**49 tests passed**.

Recovery tests cover independent snapshots, low space, unknown state, runtime
mismatch, failed trials, retry, partial desktop installation, damaged backups,
package changes during copying, namespace mismatch and errors after commit.
Old AppImage migration recovery is refused after later update/rollback, even
when the active application version again matches the migration baseline.
Protected snapshots and specific recovery commands appear in storage diagnostics.
Explicit adoption also refuses a changed executable instead of guessing a v0 version;
the public source preparation CLI is tested through preparation and rechecking.

## Asahi hardware proof

The **six-session AppImage proof passed** on Apple M1 Asahi/Fedora with
**16,384-byte pages**, Wine ARM64EC 11.20 and FEX 2610. Local evidence:
`.cage/onboarding/appimage-asahi-3/{result.json,*.png,*.log,documents/}`.

| Phase | Verified behavior |
| --- | --- |
| Historical 3.6 | Actual old launcher/installer, Unicode-named PDF open, real toolbar preference command, byte-identical Save As |
| Managed baseline adoption | Settings/documents survived; independent snapshot inventory matched the unchanged original prefix |
| Update to 3.6.1 | Candidate EXE matched its source pin; preference, prefix document and PDF save survived |
| Installed-menu relaunch | Menu dispatched to the retained package matching the committed candidate |
| Rollback to 3.6 | Baseline EXE/settings returned; latest prefix document carried forward |
| Installed-menu relaunch | Committed rollback prefix reused; original host and old prefix documents unchanged |

The local AppImages contain the initial onboarding helpers, before the later
package-copy race and post-rollback recovery guards. Final packaged runtime
qualification is recorded separately in native CI. Historical helpers are
unmodified test fixtures from Cage `10c295a`, around the pinned application seed.
This does not claim SumatraPDF was shipped by that historical Cage version.

The **native container six-session proof also passed on the same 16 KiB Asahi
host**, using actual container builds from the shared recipes and the cached
qualified Wine/FEX carrier. It verified the same historical adoption, preference,
PDF saves, pinned EXEs, update, relaunch and rollback checks with private
persistent container state. Evidence: `.cage/onboarding/container-asahi/`.
Successful private proof prefixes were discarded after saving the result.
The hardware proofs preceded the final executable-baseline refusal guard;
native CI records the final packaged helper snapshot separately.

Only successful private test prefixes were discarded after saving results.
Normal Notepad++ installs/data and the earlier desktop recovery snapshots were
untouched; failed proof evidence remains. Local Flatpak qualification was not
attempted below OSTree's existing free-space reserve; the reserve was not reduced.

Shared native startup also passed local private-container checks with and without
Podman passwd injection: caller UID/GID, private state home, nonzero task exit
status, account creation and adjustment of an existing `abc` account. These are
startup checks, not an x86 application qualification.

## Native CI

The [onboarding matrix](https://github.com/Pelagians/Cage/actions/runs/39542278230)
**passed all four jobs** at source `0ae0464` on native x86_64 and ARM64
(4 KiB pages), separately from the Asahi hardware proof. It exercises historical
Flatpak/AppImage adoption, persistent containers and standalone OCI. ARM
container/OCI tests also adopt tracked historical state; x86 container/OCI tests
qualify managed update/rollback. The independent Notepad++ regression workflows
remain enabled.

| Architecture | Format | Sessions | Historical adoption | Result |
| --- | --- | --- | --- | --- |
| x86_64 | Flatpak | 6 | Recorded desktop v0 | Passed |
| x86_64 | AppImage, clean Fedora consumer | 6 | Historical explicit desktop installation | Passed |
| x86_64 | Persistent container | 5 | Not claimed for untracked generic volumes | Passed |
| x86_64 | Standalone OCI | 5 | Not claimed for untracked generic volumes | Passed |
| ARM64 | Flatpak | 6 | Recorded desktop v0 | Passed |
| ARM64 | AppImage, clean Fedora consumer | 6 | Historical explicit desktop installation | Passed |
| ARM64 | Persistent container | 6 | Recorded native Wine state | Passed |
| ARM64 | Standalone OCI | 6 | Recorded native Wine state | Passed |

Downloaded final CI records are retained locally under
`.cage/onboarding/ci-final-{desktop-x86,desktop-arm,container-x86,container-arm}/`.
Their result JSONs were independently checked for the publisher EXE pins,
architecture/page size, expected session count, settings/documents/rollback
flags and byte-identical PDF saves. Desktop records also confirm menu relaunch.
Sampled screenshots show the rendered PDF. Screenshot capture can precede the
first completed paint; the automated checks are not pixel-rendering assertions.

Existing Notepad++ regression runs passed at the same source revision:
[Flatpak](https://github.com/Pelagians/Cage/actions/runs/39542278214),
[AppImage](https://github.com/Pelagians/Cage/actions/runs/39542278168),
[ARM64 Wine/FEX](https://github.com/Pelagians/Cage/actions/runs/39542278333), and
[update/rollback](https://github.com/Pelagians/Cage/actions/runs/39542278251).
The latter includes native x86_64/ARM64 Flatpak and clean-consumer AppImage
updates plus persistent ARM containers and standalone OCI.

Each GUI proof compares EXEs with publisher pins, saves/reopens the PDF, checks
settings, checks latest documents through rollback, and uses installed desktop
integration where available. AppImage uses a clean consumer without host Wine
or installed Cage. Evidence collection copies only logs/results/screenshots
without following Wine drive links or uploading prefixes.

These proofs cover PDF open and Save As. They do not qualify annotation editing,
printing, every document format, arbitrary old volumes, registry migrations,
runtime changes, CFW imports or arbitrary Windows applications.
