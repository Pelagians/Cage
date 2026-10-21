# Repeatable portable application onboarding

Cage uses one application recipe and the existing build graph for Flatpak,
AppImage and containers. Source acquisition is explicit; build and launch do
not download application installers. This remains an MIT-licensed, standalone
open source workflow with no Pelagian account or hosted service requirement.

## Second application: SumatraPDF

`recipes/sumatrapdf-portable.cage.yaml` is the shared portable x64 recipe.
`recipes/sumatrapdf-portable.releases.json` pins both the official ZIP and EXE
for 3.6 and 3.6.1. Application settings are redirected using SumatraPDF's
documented `-appdata` option to
`C:/users/Public/AppData/Local/SumatraPDF`. The seed disables the application's
own updater so application code stays paired with its Cage generation.
No registry migration is needed. PDF MIME handlers are offered without changing
the user's default PDF application.

The packaged upstream AUTHORS, COPYING, COPYING.BSD and source reference are
checksum-bound recipe inputs. Upstream identifies GPLv3 code and MuPDF's AGPLv3
section 13 obligations; review and fulfill the upstream source requirements
before public binary distribution. Recipe source policy is not a license grant.

```sh
# x86_64; use wine-arm64ec on ARM64 (including Asahi).
python scripts/prepare-sumatrapdf-poc.py --runtime wine
python -m cage build dist/onboarding-recipes/wine/3.6.json \
  --target flatpak --flatpak-store .cage/flatpak --output dist/apps
python -m cage export flatpak dist/apps/sumatrapdf-portable-3.6 \
  --flatpak-store .cage/flatpak --output dist/SumatraPDF-3.6.flatpak
python -m cage export appimage dist/apps/sumatrapdf-portable-3.6 \
  --flatpak-store .cage/flatpak --allow-host-access --output dist/SumatraPDF-3.6.AppImage
# The same generated recipe uses the existing container build path:
python -m cage build dist/onboarding-recipes/wine/3.6.json --engine podman --output dist/containers
```

Managed builtin Wine recipes can explicitly select `--graphics desktop` for a
shared X11 session. Both architectures reuse the native task startup, which
runs Wine as the caller's non-root UID and uses private persistent home/state
directories. The universal x86 image retains `/init` for ordinary hosted and
headless sessions; direct X11 is selected only explicitly. As with the existing
ARM path, sharing an X11 display is a deliberate desktop trust grant.

For another portable application:

1. Declare the publisher archive URL, SHA-256, redistribution policy and local
   source path. `cage sources prepare RECIPE` downloads a missing HTTPS archive
   (128 MiB maximum), verifies its bytes and safely stages it. Existing staging
   must match a fresh extraction; changed files are retained and refused.
2. Map the pinned executable and required files through existing `files`
   modules. Declare launch arguments, desktop identity and file associations.
3. Identify the application's actual settings and document directories. Use
   the existing `desktop.updates` policy for qualified user paths; never copy
   entire old prefixes or merge registry hives into a new runtime seed.
4. Pin baseline and candidate releases. Build both through the existing graph,
   then add a small application workflow driver in
   `scripts/application_workflows.py` for a real preference and save operation.
5. Run `scripts/test-onboarding-poc.py` for each claimed format and architecture.
   A successful build alone does not qualify an application.

`prepare-sumatrapdf-poc.py` derives release/runtime variants from the single
recipe. It does not create separate Flatpak/AppImage/container implementations.
The generic source command accepts `--source-id` for multi-source recipes and
`--stage-name` for existing staging conventions. Acquiring restricted installers
and applications larger than the bounded portable download remain manual.

## Supported legacy migration

An eligible source has a recorded `cage.desktop-state/v0` identity and matching
prefix marker. Keep the exact old desktop package **and adjacent export JSON**.
First export a managed baseline of the **same application version, runtime,
desktop ID and architecture**. Migration is an explicit operation, not an
automatic first-launch import:

```sh
cage migrate flatpak managed-3.6.flatpak --previous-package legacy-3.6.flatpak
cage migrate appimage managed-3.6.AppImage --previous-package legacy-3.6.AppImage
# Equivalent self-contained AppImage control:
./managed-3.6.AppImage --cage-migrate --previous-package legacy-3.6.AppImage
# Tracked native Wine container state:
cage run MANAGED_BASELINE --engine podman --graphics desktop \
  --state-dir EXISTING_STATE_PARENT --state-action migrate
```

Migration checks Wine is stopped and available space before copying. Under the
existing lifecycle lock it snapshots the entire old prefix, state record and
display preference into `legacy-snapshots/<id>/`. Copies use independent
reflinks where supported and ordinary copies otherwise. Snapshot inventories
record literal Wine symlinks without traversing external documents. Hashes are
verified before and after copying and the snapshot is flushed before trial.
The old `prefix/` remains intact. The managed candidate is seeded from its
verified package and receives only the declared settings/documents. The active
pointer advances only after a successful application exit.

Desktop package adapters retain exact old/new artifacts before deployment.
Flatpak additionally verifies the newly deployed helper sees the exact old
state directory before trial; `--state-dir` supports an explicitly nonstandard
namespace. AppImage adopts a verified historical explicit desktop installation
and keeps its receipt, icon and desktop file. Unknown or changed integration
files cause refusal. Direct, previously unintegrated old AppImages can also be
adopted; the explicit migration installs the managed baseline's menu entry.

After migration, use the existing update and rollback commands. Rollback restores
the previous generation's settings and carries the **latest** qualified documents
into that generation. Updated settings remain in the retained newer prefix;
rollback does not restore a stale document snapshot. Legacy snapshots are protected
recovery data, never build cleanup candidates. `cage storage` reports them.

### Recovery and limits

- A failed trial retains the original pointer, independent snapshot and failed
  candidate. AppImage restores old integration; Flatpak restores the deployment
  selected by the authoritative state identity.
- After interruption: `cage recover-flatpak CACHE_DIRECTORY` uses the existing
  package transaction recovery interface. For AppImage use the exact managed
  baseline's `--cage-recover-migration`. Recovery retains partial integration
  files separately and never overwrites application prefixes.
- A missing/unknown state marker, changed package, mismatched runtime or later
  managed generation is refused. An arbitrary old container volume containing
  an untracked `prefix/` is **not** supported. There is no guessed import or
  general Wine-prefix conversion. The existing explicit managed `update` path
  from a recorded v0 prefix also snapshots it before proceeding.
- Registry-dependent settings, shell extensions, drivers, licensing services,
  runtime upgrades and automatic network updates are outside this qualification.
  Existing hosted, CFW, external runner and Proton workflows retain their
  previous behavior. Managed migration applies only to opted-in supported Wine
  execution paths.
- Hash receipts bind local bytes; they do not authenticate a publisher. AppImage
  retains its explicit host-access trust boundary; Flatpak keeps scoped document
  access. Keep rollback packages/prefixes until deliberately retired through a
  separate, qualified policy.

## Repeatable qualification

`.github/workflows/application-onboarding.yml` runs on native x86_64 and ARM64.
It prepares both publisher-pinned releases, builds both existing runtime paths,
and tests installed Flatpak and AppImage plus persistent containers and OCI.
Historical launchers/installers from Cage revision `10c295a` are isolated test
fixtures, not a production downgrade option. ARM native containers and their
standalone OCI exports also exercise tracked historical state; untracked generic
container migration is refused.

The shared GUI proof opens a deterministic two-page PDF, toggles the toolbar,
saves through the real application's Save As dialog, migrates where supported,
updates, relaunches from installed desktop integration, rolls back, and relaunches
again. It checks publisher EXE hashes, saved PDF bytes, preference persistence,
both old and latest prefix documents, and the unchanged original host document.
Runs retain JSON results, per-session logs and screenshots. AppImage runs in a
clean Fedora consumer with no host Wine or installed Cage requirement. Existing
Notepad++ and hosted/container contract tests remain separate regression gates.

ARM64 CI uses 4 KiB pages; Asahi's 16 KiB host requires its own local proof and is
reported separately. Success for these two pinned portable apps is not a claim
that arbitrary Windows applications work.

Upstream references:
[settings](https://www.sumatrapdfreader.org/docs/How-we-store-settings),
[command-line arguments](https://www.sumatrapdfreader.org/docs/Command-line-arguments),
[keyboard shortcuts](https://www.sumatrapdfreader.org/docs/Keyboard-shortcuts),
[release downloads](https://www.sumatrapdfreader.org/download-prev).
