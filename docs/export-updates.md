# Safe export updates and rollback

Cage manages application packages and writable Wine state separately. Updates
are explicit, local operations: there is no account, commercial service, remote
updater, or additional runtime dependency. Keep the exact previous package or
bundle and runtime available until its rollback generation is no longer needed.

This release starts with the pinned portable Notepad++ recipe and the
8.8.8 → 8.8.9 → 8.8.8 proof. A matching profile is an application author's
compatibility declaration, not a claim that arbitrary Windows programs or
versions migrate safely. Runtime changes remain refused pending separate
qualification. External Proton runners and CFW retain their existing workflows;
they do not acquire an unqualified migration policy.

## Shared recipe policy

Both existing Notepad++ recipes now contain:

```yaml
desktop:
  # Existing ID, title, permissions and other metadata remain required.
  updates:
    profile: notepadplusplus-portable/v1
    settings:
      - drive_c/users/*/AppData/Roaming/Notepad++
    documents:
      - drive_c/users/*/Documents
```

Only the Wine account component may use `*`. Settings must select an
application-specific path beneath `AppData/Roaming` or `AppData/Local`.
Documents must select a known user document directory or its descendants.
Traversal, arbitrary globs, overlapping paths, links, special files and set-ID
files are refused. Neither registry hives nor `Program Files` can be selected.
A recipe without this policy continues to refuse changed generations.

Applications that keep essential preferences in the registry need an explicit,
separately tested migration design; this implementation does not merge hives.
The Notepad++ files mapping excludes its top-level `updater` directory, so
WinGup cannot independently replace the pinned application. This is an ordinary
shared recipe operation, applied by both desktop and container producers.

Installed binaries, plugins, self-updaters and undeclared state are not copied
into a new application seed. Disable application self-updaters where necessary
and qualify the application's actual settings and document paths before
advertising managed updates.

## State transaction

The first prefix still uses `prefix/` and a small `state.json`. Changed
packages create `generations/<random-id>/`, starting from the **new verified
seed**, then copy only the declared settings and documents. The old application
executable is never carried forward by the settings migration.

The application runs against this candidate. On a zero application exit and
successful Wine shutdown, Cage flushes candidate files and directories, then
atomically replaces `state.json` with a `cage.desktop-generations/v1` record.
That pointer selects the active and previous generations. This successful trial
session is the update's acceptance step: open a representative document, check
settings, save and close the application normally. Exit zero alone does not
establish broader application compatibility.

The identity binds the seed, runtime target, launch/recipe contract and packaged
helper/packager hashes. A launcher or configuration update can therefore create
a generation even if the Windows executable itself has not changed. Wine/FEX,
provider, architecture or carrier changes are not implicitly treated as safe.
The shared Flatpak platform is still managed by Flatpak; Cage does not provide
an atomic rollback of unrelated shared platform/security updates.

One nonblocking lifecycle lock covers preparation, the application, Wine
shutdown and commit. The application inherits the lock descriptor. Clean shutdown explicitly
unlocks the shared descriptor, including copies inherited by detached Unix
helpers; an abrupt launcher death retains the crash guard. Wine service
probes also reject running retained prefixes after an orphaned launcher. Cage
never kills an unrelated prefix to force an update through.

A failed or interrupted copy/trial leaves the previous pointer intact. Candidate
directories are retained for recovery, including any work saved inside them.
They are never silently reused or deleted on retry. `transaction.json` is an
advisory receipt; the durable `state.json` pointer is authoritative. There is no
automatic pruning of generations or failed candidates in user installations.
Reflinks reduce storage on supporting filesystems; ordinary copies are the
fallback. Budget enough space for full copies where reflinks are unavailable.

Rollback uses the selected previous package/runtime, copies its retained prefix
to another candidate, and carries the **latest declared documents** forward
from the current generation. Its old settings return, while new/edited documents
remain current. Deleted document paths are not resurrected. Both source prefixes
remain available. Files outside the prefix are never rewritten by the migration
or rollback manager. Applications retain their normal ability to edit documents
that the user opens; Cage does not make arbitrary application writes reversible.

## Flatpak

Re-export both a baseline and candidate with the current Cage. Retain their
adjacent `.flatpak.json` receipts. An older launcher cannot understand generation
state and safely refuses it. For existing v0 state, a generation-aware baseline
can be trialed explicitly; retain the old artifact and state before adopting it.

For a user installation whose installed baseline matches `old.flatpak`:

```sh
cage update flatpak new.flatpak --previous-package old.flatpak
cage rollback flatpak old.flatpak --previous-package new.flatpak
```

Append document paths to open them during the trial. The target and previous
export must have the same application ID, architecture and branch, a qualified
policy and valid local bundle/receipt hashes. The installed package must match
the supplied previous export before Cage changes deployment.

Cage first retains both exact bundles and receipts under
`$XDG_DATA_HOME/cage/package-updates/flatpak/<app-id>` (defaulting to
`~/.local/share`). `--cache-dir` selects another private disk-backed directory.
It deploys with Flatpak, then invokes the shared generation manager. If a trial
fails, deployment recovery selects the retained package matching the committed
state. It does not guess from the trial's exit code, including an interruption
after state committed.

After a power interruption, use the recovery directory printed by the command:

```sh
cage recover-flatpak /path/to/package-recovery-directory
flatpak run --user APP_ID --cage-state-info
```

The recovery journal is also in that directory if the original command was
interrupted before printing its result. An unfinished transaction must be
recovered before starting another update. Close the application before recovery.
Do not use Flatpak's data-deletion option for an ordinary uninstall or rollback.

The packaged controls also work without the host CLI:

```sh
flatpak run --user APP_ID --cage-update
# Restore the exact previous bundle/commit first, then:
flatpak run --user APP_ID --cage-rollback
```

For repository deployments, Flatpak supports restoring an older commit with
`flatpak update --commit=...`. The host Cage command above currently handles
local per-user exports; system installations and remote release publication are
not managed by it. Retain old bundles because a remote may prune old commits.
See the [official downgrade documentation](https://docs.flatpak.org/en/latest/tips-and-tricks.html#downgrading).

The existing desktop permissions remain unchanged. Normal mutable state remains
under `~/.var/app/<app-id>/data/<app-id>`, now including retained generations.

## AppImage

Install a generation-aware baseline at its stable user location, then run the
new package's explicit update action:

```sh
./old.AppImage --cage-install
./new.AppImage --cage-update -- /path/to/document.txt
./old.AppImage --cage-rollback -- /path/to/document.txt
./old.AppImage --cage-state-info
```

Close the trial normally to accept it. The installed baseline is retained at
`$XDG_DATA_HOME/cage/appimages/<app-id>/application.AppImage`. Before a trial
changes state, the new artifact is copied and hash-verified under its private
`versions/` directory. The stable menu launcher resolves the package matching
the active state pointer. This avoids replacing a menu executable separately
from its prefix transaction. A missing or altered retained package causes a
clear refusal; the state is retained.

An integration created by the original pre-generation installer must first be
uninstalled and reinstalled using a generation-aware baseline. Uninstall retains
state. For unintegrated AppImages, the same state actions work, but retain the
original artifact paths yourself. Never overwrite your only old AppImage.

Integration uninstall checks installed and retained package hashes, removes only
its own files and preserves application state and documents. AppImage continues
to have ordinary host-user access; these updates do not add a sandbox. Existing
FUSE and disk-backed extraction fallback instructions still apply.

## Containers and OCI

For the native ARM Wine/FEX bundle, retain both verified bundles and their
exact carrier image. Continue using the same persistent state directory:

```sh
cage run OLD_BUNDLE --graphics desktop --state-dir STATE
cage run NEW_BUNDLE --graphics desktop --state-dir STATE --state-action update
cage run OLD_BUNDLE --graphics desktop --state-dir STATE --state-action rollback
cage run OLD_BUNDLE --state-dir STATE --state-action state-info
```

Document arguments and `--writable-files` retain their existing meanings.
New native bundles ship a hash-bound lifecycle helper, so adding state management
does not require replacing the pinned Wine/FEX carrier. Existing bundles without
that helper retain their original launcher; rebuild them before requesting new
state actions. Container defaults remain ephemeral unless persistence is selected.

Exported native OCI application images accept `--cage-update`,
`--cage-rollback` and `--cage-state-info` through their launcher, with the same
persistent volume. Select the previous application image for rollback; retain
its digest and avoid pruning it while its generation is needed. Container/image
orchestrators remain responsible for selecting and retaining image artifacts.
There is no claim of an atomic Kubernetes rollout plus volume transaction.

Builtin Wine containers may opt into the same generation manager through
`--state-dir` or an OCI export with `desktop.updates`. The adapter wraps the
existing graphics/compatibility/launch script. It requires a digest-pinned
carrier and a safely inventoried seed. External runner/Proton updates and
unqualified runtime changes are refused. Untracked legacy OCI state at the old
volume-root `prefix/` is retained and refused rather than silently starting with
an empty managed prefix. Qualify an explicit import before opting such a volume
into generations. Default hosted, CFW and existing unmanaged OCI execution remain
on their original paths.

## Validation

`tests/test_safe_updates.py` runs actual subprocesses through the on-disk
transaction manager, including settings/document preservation, document
deletion, runtime/profile restrictions, special files/links, low-storage copy
failure, interrupted commit, failed application exit, Wine cleanup failure,
concurrent launch, a killed launcher with a surviving child, contract-only
updates and legacy-state adoption. Flatpak deployment recovery and legacy
container wrappers have separate contract tests.

`scripts/prepare-update-poc.py` derives the new recipe from the existing shared
recipe and verifies Notepad++ 8.8.9 against the application's
[published release checksum](https://github.com/notepad-plus-plus/notepad-plus-plus/releases/tag/v8.8.9).
The GUI proof compares active executables with both pinned source archives,
changes a real preference, saves an external Unicode-named document, updates,
saves/relaunches, rolls back, saves/relaunches again, and verifies that a newer
prefix document survived rollback. Screenshots, logs and generation records are
retained. No normal user application state is used.

`.github/workflows/export-updates.yml` provides native x86_64/aarch64 desktop
proofs and an ARM container proof. AppImages run in a contemporary Fedora
consumer with packaged Wine, using the extraction fallback on CI. Source tests,
built artifact tests and actual Asahi 16 KB runtime tests are separate evidence;
consult `export-update-qualification.md` for completed runs and limitations.
