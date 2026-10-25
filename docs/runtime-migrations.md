# Safe runtime upgrades

Runtime upgrades extend the existing generation transaction. A candidate starts
from the new package's verified, runtime-prepared seed and receives only declared
settings and documents. Old Windows system files and registry hives are never
transferred. The application name, version and executable bytes must match;
update the application separately after migrating its runtime.

The old prefix remains active until the candidate exits with status zero, Wine
stops and the existing durable commit completes. Copy, launch, shutdown and commit
failures retain the old active generation and the candidate for diagnosis.
Low disk space is refused without pruning recovery data.

## Bind and qualify a transition

The optional shared `desktop.updates.runtimeMigrations` list contains up to 16
directed rules, each with exactly `from` and `toRuntimeDigest`. `from` is the full
previous `cage.desktop-state/v1` identity: `schemaVersion`, `seedDigest`,
`runtimeDigest` and `contractDigest`. All digests must be 64 lowercase hexadecimal
characters. The destination runtime digest must differ from the source.

There are no wildcards, version ranges or implicit reverse transitions. The old
contract binds its recipe, runtime, seed and helper. The running state must match
that full identity, application version and profile. Historical v0 prefixes must
first use same-version, same-runtime adoption. Untracked prefixes are never
relabelled or imported. Unlisted transitions remain refused.

Generate a candidate recipe from the shared recipe, real baseline receipts and
candidate dry-run export plans:

```sh
python scripts/prepare-runtime-migration-poc.py shared-recipe.json \
  --pair baseline.flatpak.json candidate-flatpak-plan.json \
  --pair baseline.AppImage.json candidate-appimage-plan.json \
  --output candidate-runtime-recipe.json
```

Raw managed container plans and OCI records with `managedState` are also
accepted. Native ARM container plans are `metadata/native-launch.json`. The
helper refuses application, adapter, declared architecture/backend, profile and
user-data selection changes. It writes a new recipe without overwriting an
existing output or touching installations. This is a proposal, not qualification;
rebuild and export through the normal adapters before testing it.

For a later application-version update, derive from the shared base recipe and
omit the old `runtimeMigrations` rules. Those rules qualify a same-version runtime
transition, not a combined runtime/application change. The already retained
runtime-upgrade packages and their signed rules stay unchanged for rollback.

One recipe can contain separate exact rules for each adapter/architecture, whose
runtime and contract identities differ. CFW construction remains producer-owned:
Chocolatey recipes cannot opt into this portable-runtime migration path. Existing
prepared CFW, hosted, external-runner and Proton workflows remain unchanged.

After qualification use the existing update commands: `cage update flatpak`,
AppImage `--cage-update`, `cage run --state-dir ... --state-action update`, or
OCI `--cage-update`. Trusted `cage release update` uses the same transaction.
Its accepted sequence and signed artifacts are retained before the trial; failure
requires explicit recovery and never lowers the accepted sequence. There is no
new service or dependency.

## Rollback and persistence

Rollback selects the retained package/runtime and copies its prior prefix to a
new candidate. It never downgrades an upgraded prefix in place. The prior settings
are restored, newer settings remain in their retained generation, and the latest
qualified documents are carried forward. Recognized Wine document-folder links
remain literal links without traversing their host targets. Unknown links,
special files and foreign identities remain errors. No automatic cleanup removes
packages, failed candidates, signed history or rollback prefixes.

Cage's display preference remains outside the prefix. Supported custom Wine DPI
values (96–384) are reapplied to the new candidate through `reg.exe`, including
`preserve` mode and an existing custom value in automatic mode. Whole registry
hives are never copied. Other registry-dependent preferences require separate
application-profile qualification; they are not implicitly imported.

Flatpak owns deployment and its shared platform runtime. This transaction retains
the exported Wine payload and prefix, without pinning or rewinding unrelated
system-managed platform updates. AppImage still relies on host glibc and graphics
drivers. Container rollback retains the digest-pinned runtime image and mount
paths.

Before rebuilding a runtime, Cage retains each replaced build-tag image under
`<same-repository>:cage-rollback-<image-id>`. Keeping the same repository preserves
Podman's original `repository@digest` resolution when the normal version tag
moves. Existing retention tags are verified, never overwritten with foreign
images; a retention failure refuses the rebuild. Build results report
`retainedImages`. These tags add no image layers and are not automatically pruned.
The existing shell builder calls the same retention function before its build;
its build flags and publication behavior remain unchanged.
The failure was reproduced with native Podman on Asahi/16 KiB pages using
temporary tags on existing Cage proof images: replacing a tag lost its old
repository digest without retention, while the retained reference kept it
resolvable. Original image IDs, digests and tags were unchanged after cleanup.
This metadata-only check is separate from a native Wine application migration.

## Explicit repaired rollback

An immutable runtime can contain a diagnosed bug, as the original ARM FEX
shutdown defect demonstrates. Ordinary rollback still selects the exact retained
package/runtime. To restore old application settings without executing that
defect, explicitly use a separately built repair package with its own runtime
identity. The original artifact, generations and failed qualification remain
retained; this does not retroactively qualify the original runtime.

The shared optional `desktop.updates.rollbackRepairs` list uses the same exact
`from` identity and different `toRuntimeDigest` shape as `runtimeMigrations`.
It authorizes only repaired rollback, not ordinary updates. Generate it from
the old package's plan and a guarded candidate with the same application version,
executable, adapter, architecture/backend and declared data policy:

```sh
python scripts/prepare-runtime-migration-poc.py shared-recipe.json \
  --rollback-repair \
  --pair original.flatpak.json guarded-flatpak-plan.json \
  --pair original.AppImage.json guarded-appimage-plan.json \
  --output repair-recipe.json
```

Build/export that recipe normally and qualify each exact pair. No new Wine or
CFW payload is downloaded at application launch, and no existing package or
prefix is patched in place. The guarded ARM payload is the existing pinned
`wine-arm64ec-11.20-fex-2610-cage1-aarch64` runtime.

The operation first checks the previous generation for an exact repair rule.
If none matches, it can repair the active original generation after an already
completed rollback. It never searches arbitrary older prefixes. It creates a
fresh candidate from the repair seed, copies declared settings from the selected
original generation and current documents from the active generation, and
records `rollbackRepair` with source prefix, original identity and actual repair
identity. Newer settings remain in their retained generation. Windows system
files and registry hives are not imported; qualified DPI is reapplied separately.
Normal exit, Wine shutdown, storage checks and durable commit remain mandatory.

```sh
cage rollback-repair flatpak repair.flatpak --previous-package installed.flatpak
./repair.AppImage --cage-rollback-repair
cage run repaired-bundle --state-dir state --state-action rollback-repair
podman run <existing qualified mounts and options> repair-image --cage-rollback-repair
cage release rollback-repair repair-release.json --key publisher.pem --format oci
```

The OCI example uses the existing explicit state, document and display mounts;
it does not add unrestricted host access. Signed repair delivery additionally
requires a unique retained signed source package and operation-specific proof.
It retains the original release and advances the sequence high-water mark before
the trial. Explicit reuse of the exact retained repair release does not lower
that mark or duplicate history. Failed trials require explicit recovery using
the existing recovery command.

`scripts/test-onboarding-poc.py --rollback-repair` exercises repair of active
original state, normal relaunch, a changed preference, restoration from the
retained previous generation, current document carry-forward and another normal
relaunch. Source prefix bytes and generations must remain unchanged/retained.
An optional 25-session stress sequence stops at its first failure with the same
120-second shutdown deadline. Repair evidence binds the source plan, actual
runtime identities, committed audit, executable hashes and package/image bytes.
It cannot sign the original or substitute for ordinary runtime-migration proof.

Flatpak's package cache retains the export's OSTree commit alongside its bundle
hash. Repeated repair or recovery verifies the retained bytes and reuses a
deployment only when its installed commit matches that receipt. Reusing it does
not skip a requested repair trial or its Wine shutdown and generation commit
checks. Older receipts remain readable; Cage never infers an exact deployment
match from a plan identity alone.

Routine `runtime-migrations.yml` push/PR runs qualify explicit repaired rollback
on ARM and retain exact runtime migration/rollback on x86_64. ARM repair uses the
existing identified `cage1` runtime; it restores original settings and current
documents into a fresh generation while retaining the original package and
prefix unchanged. It does not execute the defective runtime after rollback or
claim that the historical runtime now shuts down correctly.

Manual dispatch defaults to `rollback_repair=true` for repaired rollback on both
architectures. To diagnose the exact original runtime, explicitly dispatch with
`rollback_repair=false`. That separately labelled diagnostic retains the original
runtime, deadlines and failure gates; its failed trials remain failed.
Repair mode signs and verifies
fetch of the repaired target only; it cannot use that proof to sign an original
baseline. End-to-end trusted repair GUI tests require independent matching
original-package evidence via `--baseline-qualification`, alongside the repair's
`--qualification`. Ledger/signature/recovery behavior is also covered by tests.
Existing CFW, hosted, external-runner and Proton paths are unchanged.

## Qualification

`scripts/test-onboarding-poc.py --runtime-migration` requires identical application
executable hashes, different runtime identities and the actual committed
migration record. Five GUI sessions cover baseline preference/save, migration,
relaunch, rollback and relaunch. Saved files, latest prefix documents, preferences
and retained generations are checked; desktop cases include menu launches.
Trusted delivery repeats this with ephemeral keys outside uploaded/served trees.

Release creation and fetch require matching runtime-migration evidence for every
rule targeting that release's runtime: both full identities, at least two
sessions per identity, identical pinned executable hashes, preserved settings,
documents and rollback, plus existing package/image bindings. An allowlist or an
ordinary application-update proof alone cannot authorize a trusted runtime change.

The dedicated `Runtime migration and rollback proof` workflow covers:

| Adapter | x86_64 | ARM64 |
| --- | --- | --- |
| Flatpak / AppImage | Wine 11.0 packaging before/after its pinned 7-Zip dependency update | Original to repaired Wine 11.20/FEX payload |
| Direct container / OCI | WineHQ 10.0 to 11.0 images | Original to repaired Wine 11.20/FEX images |

The desktop x86_64 case qualifies a packaged dependency update, not a Wine major
version change. Actual old/new `7zz` hashes must differ; ARM desktop similarly
requires different translator DLL hashes. Historical producers use source
`dd9646ab9468008e775b66a196ac91fbe023345c`, with the checked-in historical x86
Flatpak lock. x86 baseline OCI export uses the current injected manager with its
old Wine image, matching direct execution; ARM retains its sealed old helper.
CI uses private profiles/stores and uploads only records without following Wine
links, application state, documents or private signing material.

Transitions remain unqualified until their exact workflow succeeds. Existing
installed Asahi and onboarding evidence does not qualify these new transitions.
CI uses 4 KiB pages; Asahi 16 KiB acceptance must be recorded separately before
claiming a transition on the user's installation.

The [qualification report](runtime-migration-qualification.md) records completed
transitions, preservation checks and remaining hardware/regression boundaries.

## Graphics direction

XWayland remains the default. Native Wine Wayland with Wine 11 and newer is a
separate, explicit future qualification using the existing recipe, runtime
identity and generation architecture. Existing container graphics options remain
unchanged. This work neither switches backends automatically nor claims native
Wayland acceptance from X11 tests.

The future backend must qualify its exact driver build and dependencies,
compositor/socket permissions, clipboard, file access, scaling, input methods and
window lifecycle on both architectures. A backend transition needs its own proof
and retained rollback path. A Wine version number alone is insufficient evidence.
