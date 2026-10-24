# Storage controls and diagnostics

Cage separates disposable build staging from application state and retained
packages. Storage commands reuse the artifact index, export receipts and existing
prefix-generation records. They do not create a second application database,
start Wine, repair state, pull images or install dependencies.

```sh
cage storage status
cage doctor

# Preview only: no files are deleted and no new lock files are created.
cage storage prune

# Apply the same eligibility rules, with fresh validation under the build lock.
cage storage prune --apply
```

Commands print JSON. `doctor` exits with status 15 when it finds a problem;
invalid storage requests also exit 15. Busy applications are reported as busy,
not treated as corrupt. A normal preview can contain protected/ineligible items.

## Finding applications and storage

By default Cage reads `dist/.cage/artifacts.json`, adjacent Flatpak/AppImage
export receipts, and direct `dist/*.build` staging directories. Known application
IDs locate their standard Flatpak and AppImage state. AppImage installation and
Flatpak recovery-cache records under Cage's user data directory are also read.
Custom artifact roots, container volumes and recovery caches are explicit:

```sh
cage storage status --output-dir dist/my-apps
cage storage status --artifact-index /path/to/artifacts.json
cage storage status --state-dir /path/to/state/APP_ID
cage doctor --package-dir /path/to/flatpak-recovery-cache
cage doctor --bundle APP_NAME --required-free-mib 4096
```

`--state-dir` selects the exact application directory containing `state.json`,
not the parent volume. It can be repeated. `--package-dir` selects an AppImage
installation directory or Flatpak recovery-cache directory and is repeatable.
No container images or anonymous volumes are automatically discovered or pruned.

The report includes indexed source bundles, package presence, active/previous
state identities, retained generations, uncommitted candidates, lock status,
space measurements, and reasons staging is protected. `doctor` additionally
checks retained recovery-package hashes, state consistency, interrupted recovery
journals, and a requested free-space reserve. With `--bundle`, it uses existing
bundle verification and checks the selected desktop/native target architecture
and supported kernel page sizes. Available host tools are informational; their
presence does not establish application or runtime compatibility.

The reserve is a floor chosen by the caller, not a promise that a build will
fit. Ordinary prefix copies, extraction fallback and Flatpak's own free-space
reserve can require considerably more space. No platform space guard is lowered.

## What pruning may remove

New successful exports hold an adjacent `*.cage-build.lock` for their complete
build lifetime. After verifying the retained package or immutable local image,
they record `.cage-storage.json` in the context. This binds the completed
staging paths, bytes and metadata. Registration failure leaves the export usable
and reports `storage.managed: false`; that staging cannot be automatically pruned.

Only these generated payloads may be removed:

| Export | Disposable completed staging | Retained |
| --- | --- | --- |
| AppImage | `AppDir/`, `payload.squashfs` | Final AppImage, export plan, inventory and cleanup receipt |
| Flatpak | `app/`, temporary `repository/` | Final Flatpak bundle, export plan and cleanup receipt |
| OCI | Staged `bundle/`, `lifecycle/`, `linux-state.tar` | Exact local application image, source bundle, Containerfile, launcher, image ID and cleanup receipt |

```sh
# Include a custom staging directory as well as default output discovery.
cage storage prune --build-dir /path/to/export-context

# Explicitly allow very recent completed staging; still previews by default.
cage storage prune --min-age-hours 0
```

The default minimum age is 24 hours. `--apply` is always required for deletion.
Source bundles are protected; their canonical Wine prefixes are never pruned.
Original output packages must still exist and match their recorded hashes.
OCI cleanup checks the exact immutable image ID locally, independent of tag
changes; it does not pull an image to satisfy the check.

Cleanup rechecks the completed inventory while holding the producer lock.
Changed files, unknown files, application-state markers, symlinked ancestors,
mounted subtrees, special files, missing packages/images, current interpreter
paths and overlapping protected storage prevent cleanup. Recorded symlinks
inside staging are unlinked without following their targets. Deletion only
visits recorded entries: newly appearing files prevent directory removal.
An interruption or late change may leave partly removed disposable staging;
the remaining files are retained and automatic cleanup refuses the changed
inventory. It never guesses how to finish deleting unknown data.

A directory name or old export receipt alone is not sufficient evidence of
ownership. Older builds without the new completion record remain protected.
There is no automatic legacy adoption or `--force` escape hatch.

## Build-only download cache

```sh
cage storage prune --tool-cache .cage/appimage-tools
cage storage prune --tool-cache .cage/appimage-tools --apply
```

This explicit option recognizes only current pinned AppImage build-tool archive
and runtime-download hashes. Each file must have the expected name and actual
checksum and meet the minimum age. The exporter and cleanup command share a
cache lock. Unknown files, old unrecognized pins, directories, runner archives,
Wine/FEX payload caches and Flatpak SDK/runtime stores remain untouched. Stop
older Cage build processes before cleanup: older versions do not use these locks.

## User data and rollback protection

Pruning never removes prefixes, active or previous generations, older retained
generations, failed candidates, installed application packages, recovery-cache
packages, OCI images, settings or documents. All Cage application-state,
installation and package-recovery namespaces are protected. Missing rollback
packages and inconsistent state are diagnosed; no recovery is attempted by a
storage command. Use the existing explicit update/recovery controls after
retaining saved work. There is no automatic pruning of application generations.

Logical bytes and allocated stat-block bytes are reported separately. Neither
is an exclusive reclaimable-space estimate on reflink, hardlink, compressed or
snapshot-backed storage. Cleanup reports observed filesystem free space before
and after; unrelated writes and delayed deallocation can affect that change.

## Validation

`tests/test_storage.py` exercises preview/apply, package integrity, live locks,
changed bytes with restored timestamps, protected generations/candidates,
symlink and parent-swap attacks, late unknown files, corrupt records, missing
rollback artifacts, special files, exact OCI IDs, download-cache restrictions,
and CLI exit codes. The update CI workflow cleans each new export's staging
with `scripts/test-storage-poc.py`, verifies its retained artifact, then runs
the real application update/rollback proofs using that artifact.

Local validation on the Asahi 16 KB host completed:

- **512 tests and 187 subtests passed**, including wheel packaging and existing
  container, CFW-consumer, desktop and update contracts.
- Real AppImage, Flatpak and OCI exports passed preview, apply, provenance
  retention, and retained-package/image integrity checks. Receipts are in
  `dist/storage-controls-proof/result.json`; the live read-only doctor check
  also passed.
- Newly generated proof packages/images were retired by the test harness only
  after integrity checks. Current application packages, user state, documents
  and rollback data were not removed. Cleanup itself never removes a package
  or image.

CI qualification at implementation revision
`f601960bcdb90a2de5a39cf619564d6b1db8a4e9` completed successfully:

- The [storage/update CI run](https://github.com/Pelagians/Cage/actions/runs/39491693675)
  passed all three jobs on the first attempt: x86_64 desktop, aarch64 desktop,
  and ARM container/OCI. Both desktop jobs passed **512 tests and 187 subtests**.
- Both versions' Flatpak and AppImage staging were pruned before their GUI
  proofs on each architecture. Both exported OCI images likewise passed staging
  cleanup and immutable-image verification before launch.
- All six GUI proofs (four desktop formats/architectures, Cage container and
  standalone OCI) completed baseline, update, updated relaunch, rollback and
  rollback relaunch. Result records verified executable versions, the editor
  preference, exact saved external document contents, latest prefix documents
  through rollback, and three retained generations.
- Companion [Flatpak](https://github.com/Pelagians/Cage/actions/runs/39491693747),
  [AppImage](https://github.com/Pelagians/Cage/actions/runs/39491693962), and
  [ARM Wine/FEX](https://github.com/Pelagians/Cage/actions/runs/39491693916)
  regression workflows also passed. No fixes or retries were required.

Small container evidence and desktop job logs were retained locally under
`.cage/storage-ci-evidence-f601960/` and `.cage/storage-ci-*.log`; the checked
result summary is `.cage/storage-ci-verification-f601960.json`. Large desktop
package artifacts were not downloaded. These proofs qualify the pinned
Notepad++ 8.8.8/8.8.9 profile, not arbitrary applications or runtime migrations.
