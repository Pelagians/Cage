# Practical v1 implementation and qualification status

24 October 2026. Implementation is opt-in through `cage.app/v1`. This is a source
implementation with gated launch paths; **MyHarmony parity is not qualified**.
No installed user prefix, native override, host udev rule or native trust record
was adopted/reset during development. The current machine is ARM Fedora Asahi;
it cannot establish the initial native Ubuntu 24.04 x86_64 tuple.

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
| OCI | Existing build/image resolution and generation lifecycle; emitted v1 capability contract; rootless Podman/crun, keep-id, dropped capabilities, no-new-privileges, explicit host-generated seccomp, private process/IPC namespaces and read-only image. No privileged fallback, SELinux disabling or mount relabeling. | Actual Wine 11.0 startup/children, folder enforcement, supplementary group/LSM behavior, USB enumeration and hotplug. |
| Flatpak | Native finish metadata, private IPC, effective native permission inspection, pinned app/runtime commits. Host Cage's guard runs through pinned runtime Python before `/app` code and checks actual policy, runtime, app commit and host folder identities. Ordinary Cage launch never rewrites overrides. Direct raw v1 payload launch refuses; the installed host desktop entry routes through Cage. | Actual metadata/Flatseal unions, native concurrent edits, Wine USB enumeration, reconnect and desktop entry behavior. |
| AppImage | Host SquashFS extraction without AppRun/self-extraction/FUSE; package and inventory verification; private ELF materializer ABI with fixed `/app` and `/run/cage/native`; independent permitted-byte transform checks; both runtime trees mounted read-only by Bubblewrap before artifact execution. | Actual extracted Wine child loading, baseline and file scope, host LSM and supplementary-group behavior, USB enumeration and hotplug. |

All Devices exposes a live host device directory while shared memory remains
separate. Sysfs and udev enumeration data are provided read-only. Shared
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

The new `capability-parity.yml` workflow runs source tests, reference validation,
Windows probe compilation and an opt-in native Bubblewrap component probe. It
keeps AppArmor and its global namespace restriction enabled and loads scoped
permission only for a disposable test executable. It explicitly publishes the
unrun three-format/hardware gates as blocked. A component test is not an AppImage,
Wine, desktop, OCI or three-format qualification pass.

V2 release signing additionally requires successful, artifact-bound capability
cases and recorded native OS, tool, Wine and security-policy identities.
Container-userland, HTTP 403, blocked hardware and source-only results cannot
satisfy that gate. MyHarmony additionally needs an actual normal window/login,
controlled device detection/reconnect, target selection and physical
synchronization with retained hardware backups. Broad USB permissions do not
establish compatibility with every Harmony device.

## Local execution result

The full suite ran with Python 3.14.8 / zlib-ng on ARM: 677 passed, 2 skipped,
and one unchanged Chocolatey smoke-package byte-reproducibility failure. Its
source, fixture and test match baseline commit `06bff7a`; decompressed package
members match, while recompression differs with this host's zlib-ng. The isolated native Bubblewrap namespace component probe also passed on ARM;
this is not native x86_64 or Wine qualification. Subsequent focused checks cover
host desktop integration, legacy authority pins and isolated imports.
The final verification counts and retained logs are recorded in the
[local evidence receipt](local-evidence.json).

Native three-format enforcement, MyHarmony service/login, and physical device
synchronization remain blocked/not-run. No qualified v1 MyHarmony release or
production parity claim has been issued.
