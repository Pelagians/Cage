# Cage desktop export assessment and implementation plan

Assessment date: 19 October 2026, America/Vancouver.

Cage can support standalone Windows application exports without replacing its recipe compiler, module executor, or artifact model. The practical extension is a shared desktop export plan and launcher, with small Flatpak and AppImage packaging adapters. The main engineering work is qualifying Wine and its Linux dependencies outside the existing container session, handling persistent prefixes safely, and completing desktop integration.

The first proof of concept should use one checksum-pinned portable Windows application without CFW, on Linux x86_64, with Flatpak first. AppImage follows using the same application recipe and launch semantics. CFW support is a separate qualification phase because its current prepared prefix is explicitly bound to a particular Cage Wine container image. Neither an installed application nor a passing bundle verification establishes desktop compatibility.

This document proposes work only. No application, runtime, recipe, workflow, or implementation code was changed during this assessment.

## Revisions and evidence

The workspace was initially an empty Git repository. Cage was fetched into it; CFW was cloned into a temporary review checkout. The reviewed revisions matched the upstream default branches:

| Repository | Reviewed revision | Location |
| --- | --- | --- |
| Cage | [`408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0`](https://github.com/Pelagians/Cage/commit/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0) | `/home/nobodywatchin/Documents/ChatGPT/Cage` |
| CFW | [`18216a01876c509143b86f857fed3f5f72871257`](https://github.com/noahgiroux/CFW/commit/18216a01876c509143b86f857fed3f5f72871257) | `/tmp/cage-cfw-assessment-20261019/CFW` |

Both commits date to 29 September 2026. Architecture, implementation, recipes, runtime definitions, build/release workflows, contracts, and tests were inspected.

Local validation used Python 3.14.8 and the existing unittest-compatible tests:

- Cage: 429 tests executed, 428 passed, one failed. Two additional wheel-building tests were excluded because the required Python packaging tools were unavailable. The failure was `test_packaged_smoke_nupkg_matches_committed_source`: rebuilding the ZIP on this host produced different compressed bytes. All extracted members, CRCs, and timestamps matched; the host uses `1.3.1.zlib-ng`. This demonstrates a compression-dependent reproducibility assumption, not changed package contents.
- CFW: all 49 Python contract tests passed.
- A temporary synthetic bundle probe changed every byte of an 18-byte executable without changing its length. `verify_bundle()` still returned `valid=true` and `runnable=true`. This confirms the content-integrity gap discussed below.
- No Wine application, container runtime image, Flatpak, or AppImage was built or run locally. PowerShell/MinGW behavioral tests were not run. Local test results do not qualify a desktop runtime.

Current GitHub evidence is stronger for the existing container path:

- Cage's exact reviewed commit has successful [Python tests](https://github.com/Pelagians/Cage/actions/runs/36634662017), [CFW lifecycle smoke](https://github.com/Pelagians/Cage/actions/runs/36634662247), and [public package proof](https://github.com/Pelagians/Cage/actions/runs/36634662366). The public-package jobs actually ran. Their workflow installs 7-Zip and Notepad++, verifies their bundles and launch plans, and additionally executes the 7-Zip command-line program headlessly. It does not establish native desktop GUI behavior for either export format.
- CFW's reviewed commit has successful [container runtime construction](https://github.com/noahgiroux/CFW/actions/runs/36625538169) and [layer contract checks](https://github.com/noahgiroux/CFW/actions/runs/36625538248).
- The [19 October CFW upstream watch](https://github.com/noahgiroux/CFW/actions/runs/39285532465) failed because 13 unseen upstream commits include tree changes requiring review. This is a maintenance backlog signal, distinct from failure of the released runtime.
- The current [CFW v1.0.6 release](https://github.com/noahgiroux/CFW/releases/tag/cfw-runtime-v1.0.6) points to the reviewed CFW commit. Its downloaded detached manifest matches Cage's pinned SHA-256; its evidence, contract, and input-lock hashes also match. The prefix archive is **1,034,480,314 bytes compressed**. The archive itself was not downloaded or independently checked in this assessment. Older documentation mentioning v1.0.3/v1.0.5 does not supersede this release evidence.

## Existing architecture and reuse

### Cage application construction

Cage is a Python application requiring Python 3.11 or later and PyYAML. It has no GUI application configurator in this repository. Configuration currently means a YAML/JSON recipe, ordered operations, compatibility settings, and selected launch metadata. A future UI can call the same CLI/contracts; a UI rewrite is unnecessary for export support.

The existing construction path is:

```text
strict YAML or JSON recipe
  -> normalized Manifest and compatibility policy
  -> runtime resolution and source integrity checks
  -> ordered module BuildSteps
  -> container executor and verification
  -> application bundle and local artifact index
  -> container run, OCI application image, or Kubernetes manifest
```

The recipe parser rejects unknown keys and ambiguous YAML constructs. Modules cover installers, portable/files payloads, extraction, ISO resources, registry changes, DLLs, Winetricks, Chocolatey, explicit checks, and Linux scripts. The pipeline preserves their order. CFW foundation selection happens once before application operations; ordered Chocolatey actions do not each bootstrap a separate foundation. See [manifest parsing and CFW guards](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/core/manifest/manifest.py#L264-L409) and [pipeline compilation](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/builder/pipeline.py#L103-L186).

A bundle carries the normalized recipe, prefix, runtime binding, launch definition, graph, provenance, execution status, and build evidence. Some recipes additionally capture declared Linux filesystem outputs in `linux-state.tar`. These form a layer over a qualified OCI base, with absolute-path semantics; they are not automatically relocatable desktop assets.

| Existing component | Reuse in desktop export | Boundary to preserve |
| --- | --- | --- |
| `core/manifest/`, `core/compatibility.py` | Application identity, ordered configuration, Wine policy, suite entrypoints and MIME associations | One recipe model; no Flatpak-specific installer recipe |
| `core/modules/`, `core/build_step.py`, `builder/` | Source installation, files, registry, DLL and dependency configuration | Packaging consumes a completed artifact; it must not independently replay installers |
| `core/sources.py`, `core/media.py` | Checksums, media staging and safe extraction primitives | Strengthen export requirements without assuming every existing source declaration is verified |
| `artifact/bundle.py`, `artifact/inspection.py`, `artifact/graph.py` | Export input, metadata validation and evidence | Retain existing v0 behavior; add stronger desktop payload sealing |
| `artifact/index.py` | Resolve an application name to its built artifact | No new application database |
| `runtime/providers.py`, runtime catalog/cache | Runtime identity, acquisition and diagnostics | Qualify target ABI and dependency closure; a cached `wine` binary is insufficient |
| `runtime/launcher.py` | Suite selection, argv handling, Wine/wineconsole semantics | Extract a small shared contract, retaining container lifecycle behavior |
| `artifact/oci.py`, `artifact/kube.py`, CLI exporters | Plan/stage/build/result pattern and command structure | OCI/Kubernetes remain independent supported outputs |
| `compat/evidence.py`, `compat/failure_analysis.py` | Structured results and explicit failure classifications | Distinguish packaging, launch and functional behavior |

### Cage runtime and packaging

The catalog contains nine entries across Wine stable, Wine staging, and UMU with GE-Proton. Aliases resolve to versions, but ordinary version-tagged OCI references are not by themselves immutable content identities. CFW additionally binds an exact producer image digest.

Both runtime Dockerfiles inherit a digest-pinned Pelagian Shell image. Wine images install WineHQ amd64/i386 packages, Python, archive tools, font support, and pinned Winetricks. UMU images install pinned GE-Proton archives and an amd64 Debian UMU package. Runtime services preserve `/init`, s6, the `abc` desktop user, Labwc, Selkies, and Cage task receipts. Native Wine Wayland and Wine under XWayland have distinct qualification paths. UMU session-environment checks are explicitly not proof that a game works. See [runtime Dockerfiles](https://github.com/Pelagians/Cage/tree/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/container/runtimes) and [container architecture](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/docs/container-architecture.md).

The container CI selects affected catalog entries, builds candidate images, checks their actual image identity, runs session/environment and applicable real Wine window tests, checks ordered build operations, and adds rootless Podman qualification for Wine 11 before promotion. Python CI runs separately on Python 3.13. These pipelines should remain intact; a new desktop workflow should add artifact installation and behavioral tests rather than reinterpret existing container jobs as desktop coverage.

`cage run` is currently a container launcher. Both `headless` and `selkies` require `cage.selkies-wayland/v1`; headless still uses that session machinery. It copies the seed into a temporary prefix for each run. OCI export embeds the bundle and a generated launcher; its prefix can persist under `/var/lib/cage/state`. Kubernetes export describes deployment of that OCI image. There is no current Flatpak or AppImage exporter.

The downloadable legacy x86 runners offer useful checksum verification and loader diagnostics. They do not establish that their Linux library dependencies are available on every desktop.

### CFW compatibility foundation

CFW owns the Windows compatibility foundation: .NET/CLR behavior, PowerShell, Synchro wrappers, Chocolatey bootstrap, profiles, command adapters, and relevant Wine policy. Cage owns verified acquisition, replacement-seeding, application recipes, package actions, and final artifacts. This ownership is explicit in [Cage ADR 0024](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/docs/decisions/0024-cfw-prepared-runtime-provider.md) and [CFW's prepared-runtime decision](https://github.com/noahgiroux/CFW/blob/18216a01876c509143b86f857fed3f5f72871257/docs/decisions/0001-prepared-runtime-boundary.md).

The current prepared contract supports Wine 11.0 with a fresh win64 prefix. Its inputs include Chocolatey 2.6.0, PowerShell 7.6.5, Synchro 4.2.0 x64/x86, .NET Framework 4.8, native MSCoree, d3dcompiler assets, ConEmu, and other compatibility payloads. [The input lock](https://github.com/noahgiroux/CFW/blob/18216a01876c509143b86f857fed3f5f72871257/compat/runtime-inputs.json) records component hashes and the exact Cage Wine producer image.

CFW has two distinct construction/distribution paths:

1. The legacy native installer and interactive archive use `installer.c`, `mainv1.c`, `choc_install.ps1`, `winetricks.ps1`, and bundled assets. Its release workflow compiles MinGW binaries and assembles an archive.
2. The prepared producer uses `compat/build-runtime.sh`, policy/finalizer/profile files, and `compat/package-runtime.sh`. It proves Wine identity, PowerShell, both Synchro wrappers, path conversion, feature policy, and controlled Chocolatey installation/uninstallation before publishing a prefix archive, evidence and detached manifest.

The second path is Cage's supported consumer interface. Queries use the declared real Chocolatey executable through `wine`; package actions use `wineconsole` and the producer's PowerShell path. The profile loader already supports application fragments under `C:\ProgramData\Chocolatey-for-wine\application-profile.d`.

CFW's archive packer provides useful normalization: ordering, timestamps, ownership, permissions, removal of host drive mappings, and rejection of absolute symlinks. Those mechanics do not establish portability to a different Wine build or remove arbitrary application credentials.

CFW has no Flatpak/AppImage backend or qualified macOS/Proton producer. Its large collection of opt-in Winetricks functions is compatibility knowledge, not a second application recipe engine. Exporters should invoke none of these during normal application startup.

## Gaps that affect the design

| Priority | Finding | Consequence |
| --- | --- | --- |
| Required for first export | Current CFW artifacts and Cage launches bind a container/session identity | Add a separately qualified desktop target. Never bypass the existing digest/session checks |
| Required for first export | Prefix verification checks materialization/counts, not every file's contents | Create and verify a full staged payload inventory with hashes, file types, modes and link targets |
| Required for first export | No desktop dependency closure exists | Package Wine and the required Linux libraries/resources; do not assume the producer container's `/usr` exists on the host |
| Required for first export | `workingDirectory` is recorded but not applied; OCI and local launch semantics differ | Resolve safe working directory, argv, environment and entrypoint behavior in one shared helper |
| Required for persistence | OCI seeds only when `drive_c` is absent | Add seed identity, initialization locking, transactional creation and explicit upgrade behavior |
| Required for public release | Source policies and declared application versions are not complete locks or license grants | Record exact installed versions/dependencies and distribution evidence |
| Required for security parity | AppImage has no container-equivalent isolation by itself | Reject unenforceable mandatory policies or require an explicit, accurately described policy change |

The verified content gap is in [prefix materialization checks](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/artifact/inspection.py#L171-L220). A seal added at export authenticates the staged bytes from that point onward; it cannot retrospectively prove that an old bundle was never modified. Newly built, qualified exports should acquire their inventory at successful build completion. Legacy bundles need a trusted rebuild or an explicit local snapshot identity before publication.

Launch divergence is visible in the [container launcher](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/runtime/launcher.py#L426-L564) and [generated OCI launcher](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/artifact/oci.py#L643-L728). The latter duplicates compatibility handling and only selects the default application. Its seed-once logic also means replacing a package can leave the old application binaries in an existing writable prefix.

Current 7-Zip and Notepad++ recipes use unversioned Chocolatey package names. Their recipe version is not a resolved upstream application lock. For example, an example labeled Notepad++ 8.6.0 does not ask Chocolatey for that version. Package receipts help identify what was installed afterward, but do not make future rebuilds select the same dependency/install payloads.

Linux-state outputs are bound to their original base image by [archive validation and identity](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/artifact/linux_state.py). Desktop export should initially reject such bundles with the offending paths listed. Moving an `/etc` or `/opt` tree into `/app` does not preserve its semantics.

## Proposed shared export architecture

```text
Existing shared application recipe
              |
Existing ordered builder and application bundle
              |
Desktop eligibility, clean staging and target qualification
              |
Versioned export plan + sealed seed + shared launch contract
         /                            \
Flatpak layout adapter             AppDir adapter
         |                            |
flatpak-builder/repository         appimagetool
         |                            |
.flatpak or repository ref         .AppImage

Existing container run -> OCI -> Kubernetes remains available independently.
```

Use small Python modules following existing exporter conventions. No daemon, export server, new database, plugin marketplace, second graph engine, or separate app recipe language is needed.

### Shared application and target identities

A proposed `cage.desktop-export-plan/v0` should contain:

- Stable application ID, display name, package release version, observed upstream application version, and selected suite entrypoints.
- Source bundle identity and content inventory, recipe identity, source receipts, and any deliberate derivation/normalization.
- Immutable seed-prefix identity and a normalized launch contract: executable, argv, environment, working directory, compatibility and file argument behavior.
- Target OS/CPU architecture, Windows executable architecture and prefix architecture as separate fields, Wine provider/build identity, runtime payload digest, Linux ABI requirements, graphics backend and complete runtime dependency inventory.
- Capability requirements, per-format permission translation, and explicit failures for capabilities that cannot be enforced.
- State schema/generation policy, desktop metadata, distribution evidence, notices, and update channel identity when configured.
- Qualification results with the exact app/runtime/backend/host combination tested.

Keep the current graph and its OCI fields intact. Store desktop derivation and target qualification in export metadata, referencing the source graph. The exporter must never rewrite `runnerRuntime` to make a different Wine binary appear to be the original producer.

Separate **runtime target** from **package format**. Flatpak and AppImage may use the same Wine source/version and recipe while needing different Linux library builds. Shared recipes do not imply byte-identical prefixes or native runtime binaries. Reuse a built prefix only after the particular seed and target runtime pairing passes relocation and behavior tests. Otherwise build a target-compatible application variant through the same ordered module/pipeline machinery.

For the first non-CFW POC, a clean existing Cage bundle can be the source for explicitly recorded target qualification. Changes needed for target initialization happen only to a staged derivative. If that cannot pass without changing foundation semantics, stop that target and introduce a qualified build profile; do not quietly alter the existing bundle's binding.

For CFW, require the producer to create or expressly qualify the foundation under the intended desktop runtime closure. Matching the string `wine-11.0` is not enough. Keep the current CFW container contract valid and reject desktop export of its artifacts until this new producer contract exists.

### One recipe and a small metadata extension

Reuse `launch`, `entrypoints`, `fileAssociations`, source declarations and compatibility policy. Add a narrowly validated optional desktop/distribution section for stable ID, title, icon, categories, homepage, notices/license references, required capabilities and distribution scope. Keep `exports` for its existing application-output meaning.

Format-specific generated manifests are build outputs, not separate hand-maintained app definitions. A small target selection may identify a qualified runtime profile and update destination; it must not contain a duplicate installer sequence. Preserve strict unknown-key rejection and round trips for all existing recipes. Older Cage versions will not understand new fields; document that compatibility boundary rather than making parsing permissive.

Future CLI shape, not commands available today:

```text
cage export flatpak <app-or-bundle> --output <file> --dry-run
cage export flatpak <app-or-bundle> --output <file>
cage export appimage <app-or-bundle> --output <file> --dry-run
cage export appimage <app-or-bundle> --output <file>
```

Plans should report runtime downloads, size estimates, missing metadata, unsupported modules, permissions, state policy, rights status, and qualification status before invoking packaging tools. Export and publication remain separate actions.

### Runtime closure and launcher

Package the components needed to execute the application: Wine loader/wineserver, PE and Unix Wine modules, required Linux shared libraries, fonts/resources, selected graphics translation libraries, and Windows dependencies already installed in the seed. Include CFW only for recipes that require it. Distinguish build-only tools from runtime requirements using evidence, rather than deleting PowerShell/Chocolatey or shared DLLs because the main executable starts once without them.

Pin runtime source/archive hashes and tool versions. Inspect ELF imports and dynamically loaded modules/resources; scanning only direct dependencies misses Wine drivers and plugins. Check architecture and loader requirements. Do not copy a Debian container root filesystem into an AppImage or Flatpak, and do not bundle host GPU kernel drivers.

Use one small launcher implementation for both desktop formats. A Python standard-library helper is a reasonable first choice because Cage already uses Python and its OCI launcher embeds Python. Supply a pinned interpreter through the Flatpak runtime or application payload and through the AppImage payload; do not assume host Python. This trades some package size for avoiding a new language/toolchain or fragile duplicated shell logic. Measure it before choosing a later compiled replacement.

The helper must use argument arrays without shell evaluation, select named entrypoints, enforce producer-owned environment precedence, use absolute packaged runtime paths, resolve a validated Windows working directory, translate file arguments, initialize state, and return meaningful errors/exit status. Target adapters supply paths and host integration. The full Cage CLI, YAML parser and build dependencies are unnecessary at application launch.

Preserve legitimate session variables such as display, locale and audio connections while blocking accidental inheritance of a different `WINEPREFIX`, `WINEARCH`, Wine loader, DLL policy or uncontrolled library preload. Make environment ownership explicit and test it.

## Packaging the application environment

### Immutable seed and mutable state

The package contains an immutable, clean application prefix and its exact runtime/launch metadata. Wine always runs against a user-owned writable copy. Preserve the installed application's files, registry, Windows dependencies, fonts and required settings; copying only its `.exe` or `Program Files` directory is insufficient.

Use a stable application ID for state location, with distinct format-specific state by default:

| Item | Flatpak | AppImage |
| --- | --- | --- |
| Immutable seed | `/app/share/cage/<app-id>/seed` | `$APPDIR/usr/share/cage/<app-id>/seed` |
| Wine runtime | Packaged under `/app`, using a declared shared platform | Packaged under `$APPDIR/usr`, using the declared host ABI baseline |
| Writable prefix | `$XDG_DATA_HOME/cage/prefixes/<generation>` inside the application's sandbox | `$XDG_DATA_HOME/<app-id>/prefixes/<generation>` |
| Logs and cache | Application XDG locations | `$XDG_STATE_HOME/<app-id>` and `$XDG_CACHE_HOME/<app-id>` |
| User documents | Explicitly granted host files/directories or user-selected outputs | User-selected host paths; ordinary user process access |

Do not share a live prefix between Flatpak, AppImage and container executions. Different runtime paths, permissions and concurrent wineservers can corrupt state. An explicit future import/export operation may transfer selected user data.

First launch should lock initialization, copy into a same-filesystem temporary directory, verify the seed inventory, apply qualified host mapping adjustments, write a state record, and atomically promote the directory. Record source seed digest, runtime identity and state schema. Detect interrupted copies and stale locks; never treat the presence of `drive_c` alone as success.

Wine child processes and wineserver can outlive the first executable. Initialization/migration locks must be distinct from normal app instances. Migration requires the affected prefix to be idle; process tracking and shutdown must be scoped to that prefix rather than killing every Wine process owned by the user.

No setup installation or network dependency resolution should occur on ordinary first launch. A bounded Wine initialization/relocation step is acceptable only when prequalified and performed automatically with useful diagnostics.

### Configured applications and privacy

The initial export path should rebuild or consume a recipe-built application artifact. Recipe configuration already captures files, registry changes, arguments, environment and compatibility. Existing transient `cage run` sessions do not automatically become exportable configured snapshots.

A later explicit snapshot capability may capture user configuration from a stopped application. It must enumerate what is retained and removed, including documents, browser/account tokens, credentials, activation data, recent files, usernames, build paths, caches and host mappings. Do not automatically reclassify a personal configured prefix as redistributable.

Normalize only known safe paths. Preserve required registry and application state. Validate absolute and escaping relative symlinks, archive traversal, hardlinks, special files, source media mappings and case collisions. `dosdevices/c:` should remain prefix-relative. Any runtime `Z:` or dedicated file mapping must be intentional, created against the execution namespace, and must not leak producer host paths.

### Updates and rollback

Package updates and user-state migration are separate operations. A changed Flatpak/AppImage seed must not silently keep launching the old program already copied into the user's prefix.

For the POC, support a fixed application/runtime release and detect mismatched state generations. A new incompatible generation can retain the old prefix and present a clear recovery choice; do not claim seamless upgrades yet.

For supported updates, construct a new prefix from the new seed, migrate only explicitly qualified application settings/documents, verify it, and switch the active generation atomically. Back up the previous generation and associate it with the previous runtime. Never generically merge Wine registry hives or run a new Wine version over the user's only prefix. Test rollback of both package and state; rolling back package bytes alone may be unsafe.

Windows self-updaters can change installed binaries inside writable state. For managed exports, disable them through supported app configuration where available and use package releases. If an application requires self-update, declare the resulting unmanaged state and qualify it separately. Do not assume the seed hash still describes that mutable installation.

## Flatpak export

Use a maintained Freedesktop SDK/platform branch selected during qualification, with its exact build commits recorded. Install the qualified Wine payload and application seed under `/app`; retain shared platform libraries under `/usr`. Generate the application manifest, launcher, desktop file, icons and AppStream metadata, build into a local repository, then create a `.flatpak` bundle for direct installation. Later, publish a signed repository and `.flatpakref` using normal Flatpak tooling. The format adapter translates the shared plan; it does not duplicate Cage modules. [Flatpak manifest reference](https://docs.flatpak.org/en/latest/manifests.html).

**Standalone means no separately configured Cage or Wine.** The user still needs Flatpak and the declared platform/extensions. A single `.flatpak` bundle does not contain all shared dependencies or repository AppStream data. Supply runtime repository information for online installation; use Flatpak's offline repository/USB mechanism when genuinely offline installation is required. Do not advertise one application bundle as a complete offline installer. [Single-file bundle documentation](https://docs.flatpak.org/en/latest/single-file-bundles.html).

Permissions derive from requirements, with no blanket host/home access by default. Start the POC with X11 through the host's XWayland service, because the existing recipes use that Wine driver; a native Wayland-only permission set must wait for native Wine Wayland qualification. Add GPU/audio/network access only when required. A Windows file dialog must not be assumed to support portals. [Sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

Generate desktop entries using a stable reverse-DNS ID and existing suite/MIME metadata. File-manager launches should use Flatpak file forwarding/document access and pass translated paths to Wine. Test read-only files, in-place saves and save-as creation separately. For the first POC, a narrowly declared application document directory can provide reliable open/save behavior; portal-based selection should later reduce permanent access. Do not silently grant all of Documents to mask a failed chooser. [Desktop integration](https://docs.flatpak.org/en/latest/desktop-integration.html).

Use the runtime's graphics extension mechanism instead of copying arbitrary producer driver libraries. Traditional 32-bit Linux Wine components require matching multiarch/Compat.i386 and GL32 support. A newer WoW64 arrangement may reduce that closure but is a different runtime profile and needs tests, especially for CFW's x86 wrapper. Never infer “64-bit app” means “no 32-bit dependencies.” [Flatpak multiarch guide](https://docs.flatpak.org/en/latest/multiarch.html).

Flatpak handles installation and package updates; the Cage launch helper handles prefix generations. Record the platform commit used for qualification and re-test compatible platform updates. Do not freeze security updates indefinitely solely to reproduce a build. Flathub publication is optional and subject to its own review; private/local Flatpak exports do not depend on Flathub accepting the application.

## AppImage export

Generate a conventional AppDir with `AppRun`, desktop entry, icon, packaged Wine/runtime dependencies, shared launch helper, seed and metadata. Build it with a pinned `appimagetool`. `AppRun` locates everything relative to its mounted/extracted AppDir; no build-machine absolute paths are permitted. [AppDir specification](https://docs.appimage.org/reference/appdir.html).

Choose and publish an oldest supported Linux ABI baseline. Build native payloads against that baseline and test newer distributions, including actual graphics paths. Do not simply extract Debian Trixie Wine packages from the existing container and claim broad compatibility. Glibc, loader, 32-bit libraries, graphics modules and dynamically loaded dependencies need deliberate treatment. The default should use the supported host libc baseline and avoid bundling a second generic libc/loader or container stack merely to hide ABI incompatibility. [AppImage portability guidance](https://docs.appimage.org/reference/best-practices.html).

An AppImage remains a normal user process unless a separate sandbox is introduced. Removing Wine's `Z:` mapping is not a security boundary. Cage's existing `runtime.network: none` cannot truthfully become enforced offline isolation just by emitting an AppImage. Treat required isolation as an export eligibility condition: reject it when unsupported, or require an explicit recipe/export-policy choice that accepts ordinary host access. Flatpak can remain the recommended output when isolation is required. Do not add a bundled container engine or a mandatory second sandbox in the POC.

Store state outside the mounted image using XDG paths. Optional portable mode can be added later with explicit expectations about writable media and secrets; it should not be the default. [AppImage portable mode](https://docs.appimage.org/user-guide/portable-mode.html).

A `.desktop` file inside an AppImage does not guarantee menu installation. Provide a small optional user-level integration action, exposed through the packaged launcher or an installation companion, that places the AppImage at a stable user location, installs its icon/desktop entries, and registers MIME support without stealing defaults. Uninstall removes integration and package files; deleting user data is a separate explicit choice. Support existing desktop integration tools without requiring one. File movement and upgrades must not leave stale desktop commands.

Test the chosen AppImage runtime on FUSE-enabled hosts and its extraction fallback on hosts without usable FUSE. Executable permissions and `noexec` locations also need clear diagnostics. Do not promise universal double-click execution on every desktop. [FUSE troubleshooting and extraction](https://docs.appimage.org/user-guide/troubleshooting/fuse.html).

Start updates with verified replacement downloads and retention of the old artifact. Later emit embedded update information and `.zsync` metadata for standard AppImage update tools. Package signatures/trusted publisher keys and prefix-generation migration remain separate requirements; transport hashes alone do not establish publisher identity. Avoid a proprietary update daemon. [AppImage update mechanism](https://docs.appimage.org/packaging-guide/optional/updates.html).

## Compatibility with hosted execution and future macOS

Keep current container build/run, Selkies, OCI and Kubernetes defaults unchanged. Preserve their `/init` lifecycle, task receipts, CFW exact-image checks, network handling, rootless behavior and hosted integration. Desktop packages launch into the host desktop and do not need Selkies, Labwc, PixelFlux or s6. Those remain in the existing hosted adapter.

Factor shared launch semantics only with regression coverage. Correcting working-directory handling or bringing suite launch parity to OCI can be a small separately reviewable fix; it must not silently change container persistence defaults.

Cage's [documented Nereus boundary](https://github.com/Pelagians/Cage/blob/408ec2045b8a18b1ccd1a1eb2564ba7dcf720ae0/docs/nereus-boundary.md) already supports this work. Export must work from public source, local recipes and documented tools, without an account, license server, private registry or commercial control plane. Public OCI bases may remain dependencies of the existing hosted workflow. New desktop target definitions and build instructions should also be publicly available.

For eventual macOS, preserve reusable logical identity, application operations, launch/state policy, source provenance and qualification schemas. Keep Linux paths, ELF inspection, platform libraries, drive mapping, permission translation and package signing inside target adapters.

A future Darwin target would provide a qualified macOS Wine runtime, build execution adapter, `.app` layout with `Info.plist`, icons/document types, state under the appropriate user application-support directory, and signing/notarization packaging. Wine execution, graphics translation, Intel/Apple Silicon support, Windows binary architecture and CFW behavior require independent feasibility work. Linux Wine/Proton binaries and a Linux-qualified prefix cannot be presumed reusable. Apple distribution will also need a signing/notarization workflow for the intended channel. [Apple notarization documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

Do not implement a generic platform plugin system now. A target descriptor that does not assume `linux`, an adapter boundary for execution/paths, and target-specific evidence are enough to avoid a schema reset later.

## Security and compatibility limits

1. **Build inputs execute code.** Installers, Chocolatey scripts, raw shell and compatibility commands must run in a controlled build environment with explicit network policy and without publisher credentials. A strict YAML parser is not a sandbox. Keep signing credentials separate from untrusted application build steps.
2. **Hashes and signatures serve different purposes.** Bind seed, runtime, launch metadata and dependency inventories; verify downloads against pinned identities and authenticate published packages/repositories. Checksums from an untrusted source do not establish trust.
3. **Rights follow each component.** Cage declares MIT but lacks a tracked root license text. CFW C sources contain LGPL headers, but the inspected repository does not supply a comprehensive root license/inventory for scripts, DLL archives, fonts and Microsoft payloads. Add source/license notices and review redistribution evidence before public publication. A `redistributable` recipe string is not sufficient evidence, and private packaging still must respect applicable terms.
4. **CFW policies affect the result.** `installer.c` sets WebView arguments disabling sandbox features. Some historical adapters return success without implementing the underlying Windows action. Inspect which policies the actual target artifact retains; document them and test real application behavior. [Installer policy](https://github.com/noahgiroux/CFW/blob/18216a01876c509143b86f857fed3f5f72871257/installer.c#L460-L465), [legacy adapters](https://github.com/noahgiroux/CFW/blob/18216a01876c509143b86f857fed3f5f72871257/choc_install.ps1#L608-L669).
5. **Dependency acquisition is not uniformly closed.** CFW's Winetricks script has a top-level download from mutable upstream `main`, outside its hardened download helper, and legacy verbs use other download paths. Close the selected supported verbs before promising offline builds/launches. The legacy release pipeline has different pinning/replacement guarantees than the prepared producer. [Winetricks download entry](https://github.com/noahgiroux/CFW/blob/18216a01876c509143b86f857fed3f5f72871257/winetricks.ps1#L120-L148).
6. **Graphics and host services vary.** X11 access weakens desktop isolation; native Wayland, clipboard, IME, DPI, audio, printing, tray icons, USB and GPU acceleration need app-specific tests. Granting audio or devices can expose more than the feature's visible purpose.
7. **Windows compatibility stays bounded.** Kernel drivers, some anti-cheat/DRM, hardware dongles, UWP/Store dependencies, services and complex activation may be unsupported. Do not disguise failure with a successful installer exit. UMU/Proton and nested runtime sandbox behavior need their own track; defer them from the first desktop POC.
8. **Architecture is explicit.** Start with Linux x86_64. AArch64 and Apple Silicon support require an independently qualified runtime/translation strategy; this assessment does not establish one.
9. **Size and disk pressure matter.** Report download size, installed runtime size, seed size, first-use copy cost, and rollback generations. CFW's 1.03 GB compressed foundation makes optional use important. Reflinks can optimize copying where supported, with a correct ordinary-copy fallback; do not require overlays/FUSE for prefix mutation.

## Files likely to change

Names of new files below are proposals, not scaffolding to create before it is needed.

| Repository and files | Bounded change | Phase |
| --- | --- | --- |
| Cage `core/manifest/constants.py`, `core/manifest/manifest.py` | Optional validated desktop/distribution metadata; preserve existing recipe parsing | 1–2 |
| Cage `artifact/desktop.py` — new | Shared export eligibility, plan, staged inventory and target qualification | 1–2 |
| Cage `artifact/flatpak.py` — new | Manifest/layout generation and Flatpak plan/build results | 2 |
| Cage `artifact/appimage.py` — new | AppDir generation and AppImage plan/build results | 3 |
| Cage `runtime/desktop_launch.py` — new, with a small shared helper if necessary | Launch/state implementation packaged into exports | 2–4 |
| Cage `runtime/providers.py`, catalog code/data | Separate desktop runtime identity/capabilities from existing OCI binding; reuse acquisition logic | 1–3 |
| Cage `artifact/bundle.py`, `artifact/inspection.py`, `artifact/graph.py`, `builder/pipeline.py` | Optional build-time inventory and export references; preserve old graph/session semantics | 1–2 |
| Cage `runtime/launcher.py`, `artifact/oci.py` | Extract shared launch semantics and fix proven divergence with regression tests | 2–4 |
| Cage `cage/cli.py` | Export subcommands, dry-run plans and actionable failures | 2–3 |
| Cage `pyproject.toml` | Include launcher/runtime assets; keep format tools optional | 2–3 |
| Cage `compat/evidence.py`, `compat/failure_analysis.py` | Desktop functional evidence and unsupported-target reasons | 2–5 |
| Cage `core/modules/chocolatey.py`, install/package-evidence assets | Later exact package/dependency locks shared across outputs | 5 |
| Cage `recipes/`, `examples/` | One pinned portable POC recipe and desktop metadata; later qualify existing CFW recipes | 2–5 |
| Cage new desktop/export/state tests and `.github/workflows/desktop-exports.yml` | Real artifact qualification plus fast negative/contract checks | 1–6 |
| Cage README, architecture/spec docs and new ADR | Document CLI, state, runtime targets, permissions and support matrix | Each phase |
| Cage root license and component notices | Supply declared license text and distributable component inventory | Before public release |
| CFW `compat/contract.json`, `compat/runtime-inputs.json` | Versioned desktop target identity alongside retained container contract | 5 |
| CFW `compat/build-runtime.sh`, `compat/package-runtime.sh` | Target proof adapter and safe relocation constraints; retain existing producer flow | 5 |
| CFW new desktop qualification workflow, existing contract/PowerShell tests | Repeat foundation proofs on target runtime and resulting packages | 5 |
| CFW selected Winetricks paths, profiles/finalizer only if needed | Close selected downloads or fix demonstrated target failure; no general rewrite | 5 |
| CFW documentation and component/license inventory | Record target scope, redistribution inputs and maintained legacy behavior | 5–6 |

No first-phase changes are needed in CFW's interactive installer/wrapper or legacy release workflow. No wholesale refactor of `builder/executor.py`, container services or the module architecture is justified. A target-compatible rebuild adapter may later require executor changes, but only after the first runtime qualification establishes the concrete need.

## Phased implementation and acceptance criteria

### Phase 1  Establish a qualified target and export boundary

Choose one small redistributable Windows x64 application with useful open/save/settings behavior, such as a pinned portable Notepad++ release after checking its distribution payload. Use the existing `files`/portable installation path rather than the current unpinned Chocolatey recipe. Select one Wine build, a maintained Flatpak platform, and an AppImage ABI baseline.

Specify a minimal target descriptor, desktop plan, state record and dependency/rights inventory. Investigate runtime portability with disposable copies; retain the existing source bundle and original runtime identity.

**Acceptance**

- Exact app source, runtime inputs, source bundle and target identities are recorded.
- The chosen runtime executes under the selected desktop environment without host Wine or Cage.
- Required dependencies and unsupported capabilities are enumerated; container-dependent Linux state and current unqualified CFW are rejected.
- Payload tampering, escaping links, missing runtime identity and conflicting producer environment fail before export.
- Existing recipe/graph tests still pass; no existing runtime gate is relaxed.

**Decision gate:** if the candidate runtime/prefix is incompatible, build a compatible profile through the existing module interface before continuing. Do not expand the app list to avoid diagnosing the failure.

### Phase 2  Deliver one working Flatpak

Implement the narrow shared plan/launcher, seed inventory, atomic first-use state, one entrypoint, icon/menu entry, a bounded file-access policy and `cage export flatpak` with dry run. Include required helper/interpreter dependencies. Support local installation; do not require public hosting.

**Acceptance**

- From a clean account with Flatpak installed but no Wine, Cage, CFW or container engine, installation resolves declared runtime dependencies and menu launch opens the real application.
- Open a file, edit it, save it, close the application and reopen the saved file; settings survive a second launch.
- Spaces, Unicode paths and arguments work; working directory is applied.
- Launch performs no Wine/Chocolatey dependency downloads or manual setup.
- Package/seed/source bundle stay unchanged; interrupted initialization recovers; two simultaneous first launches do not corrupt state.
- The POC recipe's permissions and tested limitations are visible in the plan and documentation.

This is the first product milestone. A generated manifest or a window screenshot alone does not satisfy it.

### Phase 3  Export the same configured application as AppImage

Implement AppDir layout, relative runtime paths, optional user-level desktop integration, packaging and ABI diagnostics. Use the same application recipe, launch semantics, seed rules and evidence schema. Allow a separately qualified native dependency build.

**Acceptance**

- The same configured application passes open/edit/save/relaunch on clean hosts from at least two distribution families within the declared support range.
- No host Wine, Cage, Python installation or container engine is required.
- Relocation, spaces/Unicode, read-only package mount, FUSE operation and extraction fallback work.
- Menu integration resolves a stable executable and can be removed without deleting user state.
- Mandatory isolation policies that AppImage cannot enforce are rejected; a deliberately permitted ordinary-process mode is accurately described.
- No format-specific copy of installer/registry/application recipe logic exists.

### Phase 4  Complete desktop behavior and safe updates

Add named suite entrypoints, MIME/file-manager handoff, read-only and writable file selection, selected printing/clipboard/IME behavior, diagnostics and application update policy. Implement generation-aware updates/rollback before promising transparent updates.

**Acceptance**

- File association opens the correct entrypoint, with correct access for open, save and save-as; no blanket filesystem permission is introduced as an unexamined fallback.
- An upgrade actually runs the new application version while retaining qualified user settings/documents.
- Failed upgrade, interrupted migration, concurrent launches and package rollback retain a working recoverable state.
- A Wine runtime change cannot mutate the only copy of user state.
- Self-updater behavior is declared and tested.
- Existing OCI, container, Selkies and suite-launch behavior passes regression checks.

### Phase 5  Qualify CFW and expand compatibility selectively

CFW publishes a versioned desktop-compatible foundation target with exact Wine/runtime identities and its existing behavioral proofs. Cage consumes it through the existing verified foundation boundary. Add shared exact Chocolatey/package payload locking for release recipes and qualify 7-Zip/Notepad++ through this path.

**Acceptance**

- CFW's existing container producer, interactive build checks and Cage lifecycle jobs continue passing.
- Desktop target proofs cover PowerShell, x64/x86 wrappers, Chocolatey install/uninstall, relocation and the actual selected applications.
- Both export formats pass application workflows and persistent relaunch without bootstrap downloads.
- Old container artifacts remain valid for containers and are not silently promoted to desktop qualification.
- Public exports have component/source/license inventories and a clean prefix.
- Additional apps enter a versioned support matrix only after functional tests; failed and unsupported cases remain visible.

Add 32-bit/WoW64 variants, native Wayland, DXVK/VKD3D, .NET/COM-heavy applications and UMU/Proton in separate bounded increments. None is required to claim the first portable application POC.

### Phase 6  Release and maintenance

Add signed Flatpak repository publication, release AppImage signatures/checksums, optional standard update metadata, artifact retention and runtime security refresh qualification. Keep private/personal exports possible without publication or commercial infrastructure.

**Acceptance**

- Releases can be built from documented public source and tools without Pelagian platform credentials.
- Signing occurs after untrusted build steps and verifies the exact artifact shipped.
- A release receipt identifies app, recipe, runtime, native dependency closure, build tools and test matrix.
- Clean-host install/upgrade/rollback tests gate publication, with failure artifacts retained.
- Supported runtime security updates have a repeatable requalification path.
- A future-platform design fixture can represent Darwin target paths/runtime identity without changing application recipe semantics; it is not advertised as macOS support.

## Testing matrix and completion standard

Use existing Python tests for fast parser, plan and contract validation. Add targeted tests for input/path/argv injection, content tampering, state transaction failures, target mismatch and unsupported capability errors. Preserve the existing container runtime, CFW lifecycle, OCI/Kubernetes, rootless Podman and source integrity suites.

Real desktop tests must record application version, recipe/build identity, Wine payload, platform/dependency versions, package format, distribution, session/backend and relevant GPU. Separate:

| Evidence level | Required observation |
| --- | --- |
| Plan | Schema valid and all dependencies/capabilities resolved |
| Build | Package created and content/metadata verified |
| Install | Clean account installs with documented prerequisites |
| Launch | Real application process and usable window appear |
| Functional | Open/edit/save/reopen and app-specific task succeed |
| Persistence | Settings and documents survive shutdown/relaunch |
| Upgrade | New binary version runs and user state migrates or recovers safely |
| Isolation | Promised filesystem/network/device boundaries actually hold |

Begin with x86_64, X11/XWayland and a software/basic graphics case. Expand to GNOME/KDE, native Wayland, Intel/AMD/NVIDIA, traditional multilib/new WoW64, audio/printing and complex apps only when they become claimed support. Include offline launch, no host Wine/Cage, unusual usernames/paths, disk-full/cancelled initialization, multiple instances, corrupted payloads, and stale state. Automated headless tests should supplement real desktop acceptance.

The intended user workflow is complete only when a configured application can be exported, installed or integrated, launched from the desktop, used for its stated task, and relaunched with correct state without manual Wine/Cage configuration. Packaging success, container success and source-level compatibility claims are separate evidence and must remain so.
