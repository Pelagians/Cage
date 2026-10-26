# Practical v1 implementation and qualification status

25 October 2026. Implementation is opt-in through `cage.app/v1`. This is a source
implementation with gated launch paths; **MyHarmony parity is not qualified**.
No installed user prefix, native override, host udev rule or native trust record
was adopted/reset during development. The current machine is ARM Fedora Asahi;
it cannot establish the initial native Ubuntu 24.04 x86_64 tuple.

## Native Wayland follow-up

An explicit pinned Wine 11.0 x86_64 native Wayland candidate is being added in
PR #23. The adapter/socket/runtime checks and a separate three-format CI job are
implemented; actual qualification is pending its exact-head evidence. See
[Wayland selection and boundaries](wayland.md). X11 remains the default, and
existing installations are not migrated automatically.

## Implemented contract

- Strict v1 parsing and semantic normalization, preserving v0 parsing and launch
  paths. The supported subset is local desktop, filesystem folders, shared
  networking, X11 and All Devices. Known advanced capabilities report
  unsupported; malformed/unknown/removed fields reject. Required unsupported or
  denied capabilities block export/launch.
- `cage permissions plan RECIPE --format FORMAT`, `inspect APP --format FORMAT`,
  `bind APP REQUEST --format FORMAT --base BASE --path PATH`, and explicit
  `accept APP --format FORMAT --contract SHA256`. Binding replaces the request's
  location. Flatpak previews a native delta and adopts only a verified receipt,
  under the installation/state/authority locks. It never writes native
  overrides. Independent remaining grants and descendant holes are inspected;
  a conflicting union refuses exact replacement. Native folder unions outside
  the reviewed resolved requests refuse qualified launch; they remain untouched
  and must first be represented by a recipe request/binding.
- Canonical per-user/app-ID publisher authority in the existing release ledger,
  independent of `--cache-dir`, shared across formats. Native Flatpak ref and
  user installation identity are pinned. Publisher takeover, alternate cache
  registration, user/system conflicts and unverified retained data refuse.
  `--adopt-existing` verifies an exact v2 deployment/state; it cannot convert a
  v0/v1 prefix to a v2 identity. Use a fresh ID until such a transition qualifies.
- Signed `cage.release/v2` bindings and `cage.desktop-state/v2` compatibility.
  Exact active/previous release digests select packages, even when several
  permission-only releases share a prefix identity. Compatibility includes the
  app ID, seed, runtime closure/ABI, materializer ABI, launch/compatibility inputs
  and lifecycle profile. Publisher identity scopes these records through the
  mandatory canonical authority and signed release binding. Policy decisions,
  bindings, implementation hashes and temporary paths do not select a prefix.
  State-affecting transitions refuse pending a qualified migration. Existing
  v1 signed releases and records retain their original interpretation.

## Adapter paths

| Adapter | Implementation | Still needs native qualification |
| --- | --- | --- |
| OCI | Existing build/image resolution and generation lifecycle; emitted v1 capability contract; rootless Podman/crun, keep-id, dropped capabilities, no-new-privileges, explicit host-generated seccomp, private process/IPC namespaces and read-only image. No privileged fallback, SELinux disabling or mount relabeling. | Supplementary device group/LSM behavior, real USB enumeration/reconnect, and the MyHarmony application workflow. Generic Wine window/child, folder, network and isolation probes passed below. |
| Flatpak | Native finish metadata, private IPC, effective native permission inspection, pinned app/runtime commits. Host Cage's guard runs through pinned runtime Python before `/app` code and checks actual policy, runtime, app commit and host folder identities. Ordinary Cage launch never rewrites overrides. Direct raw v1 payload launch refuses; the installed host desktop entry routes through Cage. | Flatseal UI, native concurrent-edit integration, real Wine USB enumeration/reconnect, and managed desktop entry behavior. Native permission denial/rebinding and generic probes passed below. |
| AppImage | Host SquashFS extraction without AppRun/self-extraction/FUSE; package and inventory verification; private ELF materializer ABI with fixed `/app` and `/run/cage/native`; independent permitted-byte transform checks; both runtime trees mounted read-only by Bubblewrap before artifact execution. | Physical device group/LSM behavior, real USB enumeration/reconnect, and the full installed desktop/MIME route. Extracted private Wine/native-child loading, Unicode paths, isolation and generic probes passed below. |

All Devices exposes a live host device directory while shared memory remains
separate. OCI and AppImage add read-only sysfs and udev metadata. Flatpak uses its native All Devices surface; CI exposed USB sysfs but no `/run/udev/data`. Real Wine USB enumeration remains unqualified across all three formats. Shared
networking supplies the host event namespace for the first required-hotplug
combination. Host ACL/group/LSM authorization remains necessary. The existing
Harmony uaccess rules are reused by an explicit administrative helper with
modified-file preservation, shared owners and retained recovery copies. No
selected-device broker, portal bridge or world-writable device rule was added.

The initial managed launch gate requires Ubuntu 24.04, native x86_64, a regular
user, enabled AppArmor and local X11. Namespace authorization must be scoped to
host tools; `packaging/apparmor/cage-v1-userns.profile.in` is an administrative
example, not a policy automatically applied by Cage. Existing Docker, ARM,
Wayland and CFW v0 paths remain separate.

Host desktop integration uses a canonical owned entry invoking host Cage. It
preserves modified/untracked desktop files and keeps the first installed format
as the desktop default when other formats are added. Other formats remain
available through `cage release run --format …`. Trust/desktop stores and host
Cage's installed code are protected from recipe filesystem grants.

## Tests and evidence

`tests/test_capability_contract.py`, `test_capability_delivery.py`,
`test_capability_exports.py` and `test_harmony_rules.py` exercise normalization,
authority/cache/native identity conflicts, native binding races, state reuse,
exact release pointers, signed version boundaries, permitted interpreter
rewrites, adapter construction and host-rule preservation. Synthetic payloads
and mocked host tools test source contracts; they do not qualify a runtime.

Run the reference projection and **production v1 parser** together with:

```sh
python scripts/check-capability-contract.py
```

The test-only checker needs `jsonschema`; production parsing uses the shared
stdlib normalizer and existing application validators. It retains the v0
application comparison and checks the removed fields and semantic negatives.

`tests/probes/capability_probe.py` and `capability_probe.c` provide shared Linux
and Windows filesystem/network/device observations. Host controls must prove
the denied canaries/endpoints exist. Use disposable folders and a dedicated
recoverable device. Linux synthetic null-device tests are not Wine USB tests;
Windows HID counts alone cannot prove a particular Harmony model works. Supply
controlled-device/reconnect evidence separately. Run the shared assertions with:

```sh
python scripts/check-capability-parity-evidence.py \
  recipes/myharmony-compat.cage.yaml EVIDENCE_DIRECTORY --output parity.json
```

The directory contains `host.json` plus each format's `.linux.json` and
`.windows.json` probe reports. Host `controls` records independent readable
canaries, writable fixture, TCP/abstract endpoint and dedicated-device control
observations. Missing controls/probes/hardware yield **blocked**. A failed
observed assertion yields **failed**. This report qualifies neither the actual
application workflow nor synchronization.

The `capability-parity.yml` workflow runs source tests, reference validation,
Windows probe compilation and an opt-in native Bubblewrap component probe, then
an independent actual-runtime job. Both jobs keep AppArmor and its global
namespace restriction enabled and load scoped permission only for a disposable
test executable. Missing runtime observations and hardware gates remain blocked.
A component test alone does not qualify an adapter.

`scripts/test-capability-runtimes.py` builds one pinned Wine 11 desktop bundle,
exports real Flatpak and AppImage packages, and separately builds and exports a
digest-pinned OCI image. These local producer candidates run through the actual
host-managed adapters, including native Flatpak inspection/guard and AppImage
import/materialization. They bootstrap runtime evidence without inventing a
prequalified signed release. They do not test release installation authority.

For each format, a Windows x86_64 application creates an X11 window, runs the
Linux probe as a native child through Wine, and persists a counter in its active
prefix. Three launches cover shared networking/All Devices, denied optional
networking/devices, and replacement of a writable folder. The Linux and Windows
probes check read-only/read-write scope, unrelated and protected canaries,
network endpoints and the current Wine drive alias. Native observations also
check read-only package/runtime mounts, privilege/syscall boundaries, private
process/shared-memory views and synthetic device removal/reappearance.

Every run uses a fresh app ID, isolated XDG/Flatpak/container stores and disposable
folders. The first prefix is copied to a retained recovery fixture; later launches
must preserve its inventory hash and exact generation record while the active
counter advances. Only the test's owned synthetic null device, shared-memory
canary and sentinel process are cleaned up. No existing user prefix, native
override or recovery data is touched. The synthetic device is an owned alias of
`/dev/null`; it neither sends USB commands nor qualifies Harmony protocols,
physical reconnect or synchronization. The shared report deliberately keeps
those hardware cases blocked.

V2 release signing additionally requires successful, artifact-bound capability
cases and recorded native OS, tool, Wine and security-policy identities.
Container-userland, HTTP 403, blocked hardware and source-only results cannot
satisfy that gate. MyHarmony additionally needs an actual normal window/login,
controlled device detection/reconnect, target selection and physical
synchronization with retained hardware backups. Broad USB permissions do not
establish compatibility with every Harmony device.

## Actual runtime CI result, 25 October 2026

The [complete x86_64 workflow passed](https://github.com/Pelagians/Cage/actions/runs/40181626183)
on exact source `a8104abb1268fcbf37d44e1ea7f9777abe0062f6`. The
[runtime CI receipt](runtime-ci-evidence.json) binds source, package/image and
native ref identities, host/tools/policy, artifacts and retained evidence hashes.
It preserves the earlier source/component receipt as history.

| Adapter | Shared network/All Devices | Network/devices denied | Writable folder rebound | State/recovery |
| --- | --- | --- | --- | --- |
| OCI, rootless Podman/crun | Passed | Passed | Passed | Counter 1 → 2 → 3; same prefix and generation record; recovery hash preserved |
| Flatpak | Passed | Passed | Passed | Counter 1 → 2 → 3; same prefix and generation record; recovery hash preserved |
| AppImage, host Cage/Bubblewrap | Passed | Passed | Passed | Counter 1 → 2 → 3; same prefix and generation record; recovery hash preserved |

All nine scenarios executed a Windows x86_64 probe under Wine 11.0, observed its
normal X11 window, and ran its native Linux child in the same boundary. Positive
and negative observations cover read-only/read-write folders with Unicode/spaced
paths, Wine drive aliases, old-folder removal after rebinding, unrelated/protected
canaries, host TCP/abstract endpoints, immutable package/runtime mounts, dropped
capabilities, no-new-privileges, seccomp, and hidden host process/shared-memory
canaries. Owned synthetic null nodes exercised live removal and reappearance.

Runtime failures found and fixed during qualification included legacy v0 network
verification applied to v1, OCI shared-memory copy-up and private-network Xauthority
lookup, Flatpak resource-directory defaults from its pinned runtime, and the
AppImage extractor's version exit convention and missing private UTF-8 locale.
The harness now reads initial compact state through the existing generation
manager without rewriting it. The managed AppImage locale belongs to the hashed
private closure; existing user prefixes were not migrated or reset.

The tuple was Ubuntu 24.04.5 x86_64, kernel 6.17.0-1022-azure, X11/Xvfb,
Wine 11.0, Podman 4.9.3/crun 1.14.1, Flatpak 1.14.6 and Bubblewrap 0.9.0.
AppArmor stayed enabled and its global unprivileged namespace restriction stayed
at `1`. Source validation passed **689 tests and 265 subtests**, with one opt-in
component skipped in that suite; the dedicated namespace component passed
separately.

**Physical USB synchronization remains unqualified.** The shared observation
report passes baseline/filesystem/network for each format and keeps controlled
physical-device detection/reconnect blocked. No real Harmony hardware was used.
Flatpak's absent udev database is a recorded enumeration-surface difference whose
adequacy for actual Wine/Harmony detection still needs hardware evidence. HID
counts and synthetic node tests cannot qualify USB protocols, target selection,
login, synchronization or every Harmony model. These producer-candidate launches
also do not qualify signed release installation/adoption or every acceptance
specification. No qualified v1 MyHarmony release was issued.

## Earlier source/component CI result, 25 October 2026

The new [Ubuntu x86_64 workflow completed successfully](https://github.com/Pelagians/Cage/actions/runs/40171367024)
on source commit `584f5ae`: **679 tests passed, one opt-in component test skipped**
in the general suite, plus **260 passing subtests**. The dedicated native
namespace component then passed separately. The Windows x86_64 probe compiled
with warnings treated as errors. The reference checker accepted 16 field
projections, rejected 47 structural negatives, and retained the 45 acceptance
specifications without treating them as runtime passes.

CI fixes installed the wheel-test backend explicitly, guarded the compiler's
Unicode definitions, and made signature tests respect the optional releases
dependency in existing base packaging jobs. The new workflow installs that
dependency and executes the signature tests. AppArmor stayed enabled, its global
unprivileged namespace restriction stayed at `1`, and only the disposable test
executable received scoped namespace permission.

The [CI receipt](ci-evidence.json) binds the run, exact tested source, artifact,
OS/tool versions and retained evidence hashes. Existing local app state, USB
rules and recovery data were not changed. The earlier local receipt below is
retained as development history.

**That earlier uploaded report marked every adapter case blocked.**
This successful source/component job does not qualify full OCI/Flatpak/AppImage
runtime parity, MyHarmony login or physical USB synchronization. Real dedicated
hardware and retained backups are still required before synchronization can be
qualified. No qualified v1 MyHarmony release was issued.

## Local execution result

The full suite ran with Python 3.14.8 / zlib-ng on ARM: 677 passed, 2 skipped,
and one unchanged Chocolatey smoke-package byte-reproducibility failure. Its
source, fixture and test match baseline commit `06bff7a`; decompressed package
members match, while recompression differs with this host's zlib-ng. The isolated native Bubblewrap namespace component probe also passed on ARM;
this is not native x86_64 or Wine qualification. Subsequent focused checks cover
host desktop integration, legacy authority pins and isolated imports.
The final verification counts and retained logs are recorded in the
[local evidence receipt](local-evidence.json).

This earlier local receipt did not run three-format enforcement. The later CI
result above covers generic runtime probes; MyHarmony service/login and physical
device synchronization remain unqualified. No qualified v1 MyHarmony release or
production parity claim has been issued.

## Installed release follow-up

The [installed-release qualification specification](installed-release-qualification.md)
adds independent OCI, Flatpak and AppImage CI cells for fresh signed installation,
explicit policy-contract updates, exact release rollback with current revocations,
native folder rebinding, recovery/relaunch, installed desktop Exec/document
forwarding and verified adoption with state preservation. It retains the existing
All Devices producer runtime job. The signed installed fixture requests no devices;
controlled Windows device/hotplug cases remain blocked and the signing gate is
unchanged. Harness presence is not a pass: consult the exact commit's retained
`installed/installed-release.json` for results. Physical USB synchronization and
the actual MyHarmony workflow remain unqualified.
