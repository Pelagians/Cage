# Installed desktop qualification on Asahi

Completed on 22 October 2026 (local time): **48 successful native GUI sessions**
across both applications and both formats. Independent package, signature and
portal checks passed. All **25,112 pre-existing protected entries** and the
normal installed Flatpak commit are unchanged.

## Platform and inputs

The test machine is an Apple MacBook Pro (13-inch, M1, 2020), running Fedora
Asahi with kernel `7.1.13-402.asahi.fc44.aarch64+16k`, **16,384-byte pages** and
glibc 2.43. Applications run on the native machine in installed Flatpak sandboxes
and mounted type-2 AppImages. The display is a private native Xvfb at 1920 × 1440
with 192 logical DPI. These are software-rendered desktop proofs; they do not
qualify the user's Wayland session or GPU acceleration.

SumatraPDF 3.6/3.6.1 packages and the historical manager fixture were produced on
this machine from `0c3d68a`. Notepad++ 8.8.8/8.8.9 application seeds come from
[the completed CI proof](https://github.com/Pelagians/Cage/actions/runs/39877572840),
source `cb45cba`. The original package hashes were checked against independently
verified signed CI records. Following the cross-login failure described below,
their exact seeds were rematerialized into private QA bundles and re-exported
through the standard exporters with the corrected helper at `873b7cf`. Their
manifests, runtime targets and entire seed inventories remain identical to
the original CI exports. The QA provenance identifies those verified source
packages and records that the local installer pipeline was not re-executed.
The proof drivers are from `c8f3267`; their changes keep fixtures inside ordinary
prefix directories and reuse optional kernel equality sharing after successful
shutdown. Neither change alters a production launcher or a qualification gate.

Both formats use `wine-arm64ec-11.20-fex-2610-cage1-aarch64`. All four current
AppImages mounted through **real FUSE**, with extraction fallback unset, and
contained the fixed FEX DLL:

```
8e84d8deb007e6951e10696d9fe19e8dc7ca6044406220effd7503d4ab218b6a
```

Evidence: `.cage/asahi-installed-qualification/hardware.json`,
`notepad-ci-packages.json` and the four `*-fuse.json` records. Producer packages
and their receipts are in `dist/asahi-installed-20261022/`; corrected Notepad++
exports and seed-reuse bundles are in `dist/asahi-installed-873b7cf/`.

## Cross-login document mapping repair

The original CI Notepad++ Flatpak opened and saved normally on Asahi, but its
update was correctly refused. Its seed was built as `runner`; Wine created
`drive_c/users/<consumer>/Documents` pointing to the consumer's host Documents
directory. The shared migration manager previously rejected every link at a
declared document path. The original active generation and incomplete candidate
remain retained, and the failed attempt is excluded from successful qualification.
The original proof driver also created a new `~/Documents/local.txt` fixture by
following that mapping. Its exact bytes were moved into the failed attempt's
evidence after identifying its creation, inode and contents; no pre-existing
document was removed. The repaired driver selects an ordinary directory inside
the private prefix for this fixture.

The shared helper now recognizes only literal mappings from a Wine account's
standard Documents/Desktop/Pictures/Music/Videos folder to that same folder in
the current host home. It copies the link itself without reading, importing or
modifying its target. Account/parent paths must remain ordinary directories.
Relative links, arbitrary targets, nested links and linked settings remain
refused. Candidate replacement only unlinks an accepted link; it never deletes
its target. Custom XDG folder mappings remain conservatively unsupported.

Four transaction/security regressions cover real update and rollback, host-file
preservation without link traversal, rejected arbitrary/internal/relative links,
linked settings and a changed destination during rollback. The complete source
suite passed **579 tests and 197 subtests** at `873b7cf`; evidence is
`.cage/asahi-installed-qualification/unit-tests.log`. Existing container adapters
reuse the same helper; CFW ownership and hosted execution are unchanged.
The same complete suite passed after the driver changes; evidence is
`unit-tests-with-harness.log` alongside the earlier test log.

## Native application matrix

| Application | Format | Ordinary installed flow | Signed delivery |
| --- | --- | --- | --- |
| SumatraPDF 3.6 → 3.6.1 | Flatpak | Passed, six sessions | Passed, five sessions |
| SumatraPDF 3.6 → 3.6.1 | AppImage | Passed, six sessions after space refusal | Passed, five sessions |
| Notepad++ 8.8.8 → 8.8.9 | Flatpak | Passed, eight sessions | Passed, five sessions |
| Notepad++ 8.8.8 → 8.8.9 | AppImage | Passed, eight sessions | Passed, five sessions |

The existing application drivers are reused. Sumatra's ordinary proof includes
supported legacy adoption, a real preference change, exact PDF Save As bytes,
application update, menu relaunch, rollback and another relaunch. Notepad's
ordinary proof additionally exercises 192-DPI persistence, MIME/desktop file
forwarding, a read-only original, Save As, a new file and a selected writable file
that is saved and reopened. Its selected-file fixtures are outside the permanent
Documents grant; the native document portal forwards the selected files, and
the unselected sibling remains inaccessible. Package filesystem permissions are
not broadened; the portal grants access to the selected files.

Every trusted case installs from signed loopback HTTP delivery, updates and
rolls back, then inspects the retained cache after the server stops. Acceptance
requires the expected EXEs, preserved preferences and document bytes, retained
generations and signed releases, menu relaunches, and sequence high-water mark
two after rollback. Application closure requires an actual successful process
return and an idle lifecycle lock. Shutdown timeouts and data checks are unchanged.

An independent pass rehashed all eight current packages against their export
receipts and upstream EXE pins, counted the 48 numbered session logs, verified
**eight detached Ed25519 signatures across 20 trusted sessions**, and checked
the retained sequence high-water marks. It also inspected the actual portal
paths after file forwarding: both selected read-only/writable files had the
expected bytes inside the sandbox, while the unselected sibling was hidden at
both the portal path and original host path. All three Notepad++ generations in
each format retain the literal host Documents mapping. Evidence:
`verified-installed-matrix.{json,log}` and
`verified-native-trusted-evidence.json` in `.cage/asahi-installed-qualification/`.

Native Notepad++ Flatpak update and AppImage baseline captures visibly show
matching readable menus, editor text and control borders at 192 DPI. Saved PDF
rendering is visible in the native Sumatra rollback captures. Xvfb's screen saver
was disabled for these captures. AppImage's DRI3/device warnings are consistent
with this private software-rendering setup; acceleration is not claimed.

The actual proof paths are recorded in
`.cage/asahi-installed-qualification/phase-results.json`. Persistent test
evidence and AppImage profiles are under
`~/.local/state/cage/asahi-installed-20261022/`. Flatpak profiles use freshly
generated proof tokens under the per-application data directory; saved shims
identify their exact paths. The Flatpak installation store is the separate
`.cage/flatpak-arm64`, rather than the user's normal installation.

## Storage and retained refusal

The initial filesystem had roughly 1 GB available. Cleanup retained installed
applications, normal settings/documents, OCI application images, the exact old
native carrier and the existing desktop recovery snapshot.

Ten obsolete private test-state trees were archived with per-file hashes, modes
and symlink targets verified before their expanded copies were removed. Their
4,422,870,169 bytes of inner archives were then consolidated losslessly into a
1,375,217,940-byte outer archive. Every inner SHA-256 was checked, and the new
archive and receipt were synced before removing redundant inner copies:

```
.cage/retired-proof-state/retired-test-states.tar.zst
SHA-256: 0acdd654a360ec1a469df167f87f9a6599d1b34f14c8d2bfed178fb347160c46
```

The retained receipts and README describe the two-stage restore, including the
outer decoder's bounded 700 MB memory allowance. Two stopped Cage tool
containers, five untagged runtime build intermediates and an unused GUI-tool
image were removed after checking their ownership and references. Both OCI
application images, the legacy carrier, RPM inputs and cached native tools remain.

Two more unused scratch trees—the x86 AppImage inspection and secondary ARM
Flatpak consumer store—were archived separately with every file hash, mode and
link target checked and the archives synced before removing expanded copies.
Their leading-dot archive names and single-stage restore instructions are in the
same README. Four obsolete CI download trees were consolidated into
`old-ci-downloads.tar.zst` (226,763,440 bytes), with the same verification and
durability checks. Its 256 MiB window requires the documented bounded 350 MB
decoder. The active native Flatpak store, Python environment and tools remain.

Completed export staging was cleaned through Cage's existing receipt and lock
checks. Pristine source bundles and interrupted build copies were retained.
Default archive-mode Flatpak export initially hit OSTree's reserve; a temporary
filesystem was also too small. A supported local `bare-user` build repository
allowed sharing unchanged files without lowering the reserve. This is a local
producer arrangement, not a new consumer dependency or packaging format.
See [OSTree's local build repository guidance](https://ostreedev.github.io/ostree/buildsystem-and-repos/).

Retaining native proof generations used additional space. One AppImage attempt
completed its first real save/close, then correctly refused migration: it needed
2,571,885,431 bytes and found 2,039,390,208. Its existing prefix, preference,
original and saved PDF bytes remained available. This failed attempt is retained
and is excluded from successful qualification. The retry uses a fresh profile;
the old profile is neither moved nor overwritten.

Kernel-verified equality sharing reclaims duplicate Windows-runtime and package
extents in task-owned copies. Every independent file, generation, setting and
document remains present; differences are retained. Completed profile sharing
holds the lifecycle lock and checks that the generation record is unchanged.
This does not remove rollback packages or alter consumer pass/fail conditions.
Cleanup initially brought available space from roughly 1 GB to about 7.7 GiB.
After the new packages and retained qualification data, about 3.3 GiB remains.

## User-state protection and boundaries

Before qualification, 25,112 existing entries were recorded with content hashes,
modes and literal symlink targets. Protection covers the existing Notepad++ data,
installed AppImage state/packages, launchers and desktop recovery tree. The
normal installed Flatpak commit was also recorded. The final comparison passed:
all 25,112 entries have unchanged contents, modes and literal link targets, and
the normal Flatpak commit is unchanged. The only additions within previously
existing protected trees are three new private proof-token roots. Evidence:
`.cage/asahi-installed-qualification/protected-state-after.{json,log}`.

The existing desktop recovery snapshot
`~/.local/share/cage/desktop-recovery/20261021T004011Z` remains protected. These
tests do not update the user's existing installations or qualify migration from
the previous runtime pin. Cross-runtime prefix migration remains refused with
data retained. The repaired Notepad++ claim covers the paired re-exports with
the repaired helper; older package contracts are not automatically enrolled or
requalified by these tests. Old helpers still refuse the document links.
Supported historical-manager adoption uses the same pinned
runtime as its target. The two portable applications are the compatibility scope;
other Windows applications and other ARM devices require their own qualification.

The earlier intermittent OCI status 247 remains a separate unexplained CI
failure followed by a strict successful retry. Native desktop qualification
does not establish its cause. No production publisher key, public binary release,
CFW change or hosted/container workflow replacement is part of this work.

The repaired helper's [onboarding matrix](https://github.com/Pelagians/Cage/actions/runs/39898584088)
and [Flatpak regression](https://github.com/Pelagians/Cage/actions/runs/39898584032)
passed at `873b7cf`. At `c8f3267`, [all four update jobs](https://github.com/Pelagians/Cage/actions/runs/39900719833),
the [AppImage regression](https://github.com/Pelagians/Cage/actions/runs/39900719766)
and [ARM Wine/FEX proof](https://github.com/Pelagians/Cage/actions/runs/39900719765)
passed. The follow-up onboarding matrix at `c8f3267` was still running its ARM
desktop job when this report was finalized; its other three jobs passed.
The earlier ARM runtime download returned HTTP 503 before application testing;
the unchanged current-source retry passed with checksum checks intact.
