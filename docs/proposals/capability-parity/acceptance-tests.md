# OCI Flatpak and AppImage parity acceptance tests

Status: design specifications, not implemented runtime tests or passed results.
Structural validation of the proposal does not qualify application behavior,
desktop integration, physical hardware or enforcement.

## Shared procedure and scope

Run one shared semantic assertion set through each claimed adapter: OCI with its
generated deployment contract, installed Flatpak, and AppImage imported/entered
by host-installed Cage. B is the reduced foundation; Q cases run only when their
capability is claimed. A missing prerequisite or unsupported outcome can pass a
refusal test, never the corresponding positive capability test. A three-format
claim needs all three positive results for the same declared scope. Do not treat
a passing foundation as completion of MyHarmony's application/USB goal. V1 always
enforces the fixed baseline; there is no recipe-level unenforced execution mode.

Use isolated temporary state, approved folders and sibling canaries. Run native
Linux and Windows probes inside the same application boundary, including child
processes. A host control process proves that denied resources exist and would
otherwise be accessible to the user. Record observed access, not merely flags,
missing files, Wine drive aliases or socket presence. Use safe synthetic devices
for permission checks; physical tests use dedicated recoverable hardware. Never
probe with secrets or destructive writes to arbitrary host devices.

Record each case's input, expected and observed result, artifact/runtime/contract
and deployment identities, effective policy, host/tool versions and outcome:
passed, failed, blocked, not-run or justified not-applicable. Reuse existing
qualification receipts with these fields; no separate test database is required.
Keep logs free of credentials, document contents and raw device serials.

## Qualification tuples

| Dimension | Required treatment |
| --- | --- |
| CPU/runtime | Native Linux x86_64 first; exact Wine provider/version, prepared-state ownership and dependencies per target. Each other architecture/emulation path is separate. |
| OCI | Select concrete rootless engine/runtime versions and user/device/LSM settings. Podman and Docker qualify independently; one engine does not qualify OCI generally. |
| Desktop | Qualify X11 and Wayland separately against Wine's actual graphics backend. Record the protocol's real scope. |
| Host policy | Record kernel/user namespace support, groups, ACLs, cgroups and SELinux/other LSM behavior. No implicit relabeling, privileged mode or policy disabling. |
| Flatpak/portals | Record Flatpak, Flatseal, portal interface/backend and Wine bridge versions for each relevant claim. |
| AppImage | First path: host Cage plus host Bubblewrap and trusted host SquashFS extraction. FUSE and artifact self-extraction are outside that initial qualification. |
| Resource host | Local Linux desktop first. Remote/VM engines, headless use and client-resource forwarding remain separate unsupported environments until qualified. |

Publish supported tuples, not the Cartesian product of successful components.
A preflight refusal is required when a tuple cannot enforce the remaining
boundary. Test versions and mechanisms are evidence; schema validity is not.

## Planner and validation

| ID | Scenario | Required assertion |
| --- | --- | --- |
| PL01 | Normalize equivalent YAML/JSON twice; migrate v0 network/Documents intent | Stable canonical identity/defaults; v0 unchanged; none maps to absence and host to the single network request. Bridge requires explicit approval of host IP/abstract scope or remains v0. No implicit widening. |
| PL02 | Unknown/removed fields, duplicate keys/IDs, invalid selectors/ranges/paths/bus names, mixed v0/v1 intent | Reject before engine invocation or prefix/host-rule mutation. Include execution `isolation` with any former value, network `mode`, filesystem `missing`, portal `lifetime`, and USB `presence: required` without `required: true`. Structural and semantic negatives remain distinguished. |
| PL03 | Known unsupported request, missing prerequisite, enforcing admin ceiling, or remote client-local binding | Required blocks target export/launch; optional may be omitted with a precise report only if denial and baseline remain enforceable. Unknown/malformed requests always reject. No broader or ordinary-process fallback. |
| PL04 | Export supported realizations for all three formats | Same normalized permission contract and app ID; separate runtime/artifact/deployment identities and support tuples. No reuse of another runtime's qualification. |

## Filesystem foundation

| ID | Scenario | Required assertion |
| --- | --- | --- |
| FS01 | Read-only folder; read, write, rename, delete and sibling probes | Reads work; mutation/sibling access fail; host inventory unchanged. Windows alternate paths cannot bypass enforcement. |
| FS02 | Writable folder; Unicode/spaced filenames, temp files, fsync, atomic replacement and sidecars | Exact content survives relaunch; only approved scope is available. |
| FS03 | Traversal, escaping symlink, replaced/unmounted resource, protected state/policy path or overlapping wider grant | No namespace escape or unaccepted broader path scope; defined missing/rebind result and retained recovery data. Permission authorizes the approved path, not a permanent inode; no claim to prevent every host-side race within intentionally shared writable content. |
| FS04 | Missing folder with optional/required and create/no-create variants | Optional omission or required launch refusal; only approved writable creation succeeds. No read-only creation, substitute folder, recursive chown or unrelated relabeling. |
| FS05 | Change Harmony -> Remote Backups while stopped; include independent old-path user/other-request grants, denial of the new location and an interrupted transaction | Resolve binding before final rules; exact replacement grants new and denies old when nothing else grants old. Flatpak delta suppresses the exact old manifest path; adding a new grant or denying home alone is insufficient. Preserve independent grants and show the union; accept remaining scope or refuse exact replacement. Cage never writes native overrides. Concurrent native edits before/during adoption invalidate the snapshot; reconciliation never restores native grants. State retained and revocations not undone. |

## Network and IPC composition

| ID | Tier and scenario | Required assertion |
| --- | --- | --- |
| NET01 | B: network absent; test host/external TCP/UDP/DNS, IPv4/IPv6, inherited handles and IPC proxy routes | Host/external IP and undeclared proxy access denied. Private in-sandbox loopback may work as recorded. Approved delegated-service effects are explicit; no absolute information-flow claim. |
| NET02 | B: single network grant via native host sharing; controlled DNS/TLS endpoint plus NET04 | Expected traffic succeeds; host loopback/network scope is disclosed and accepted. No domain/LAN/port filtering claim. Outage/HTTP 403 is a service failure; TLS success alone is not a pass. |
| NET03 | Q: application LAN discovery/inbound behavior using the same network grant | Required app topology works subject to host firewall/service conditions. No second mode or restricted-port guarantee; an unrepresentable stricter request is unsupported. |
| NET04 | B: network absent/granted with host IP and abstract Unix fixtures, including one started after launch; unrelated filesystem socket and explicit conflicting service denial | Absent: host IP/abstract access denied. Granted: abstract/IP fixtures are reachable as allowed by endpoint authorization, including late services; report this declared scope. Ungranted filesystem socket stays unavailable. A filtered bus connection alone does not imply global bus/host-command denial. Surface conflicts with explicit stronger user/admin denial; never silently waive the denial or claim stricter isolation. |

## Devices and selected USB (separately qualified)

| ID | Scenario | Required assertion |
| --- | --- | --- |
| DEV01 | No device grant; then each claimed class with available/unavailable host authorization | Exact stated class scope and independent host access. All Devices excludes separately controlled shared memory and adds no root/capabilities/privileged mode. Supplementary group/LSM behavior is tested per engine; native class metadata appears in Flatseal. |
| DEV02 | Startup-only versus required-hotplug; attach after launch, disconnect and reconnect with changed node numbers | Record concrete node/device-control, enumeration and event-delivery mechanism. Required-hotplug positive success is necessary for its claim; static mappings or an unsupported result do not pass it. Startup-only promises availability at startup, not exclusion of later devices within a broad granted class. |
| USB01 | Selected USB allow/range/exclude/interface and serial binding; matching, unrelated and identical fixtures | Exact mode exposes only matching interfaces; identity acquisition is qualified and unrelated access denied. Multiple allowed devices do not imply that Cage chooses the app's sync target. No serials in default logs. |
| USB02 | Required access with optional presence; later attachment and declared/undeclared recovery identities | Supported access permits initial waiting; matching authorized devices recover, undeclared identities remain denied in exact mode. Known denial/unsupported access blocks rather than waiting. Test physical behavior separately in APP02. |
| USB04 | Narrow direct access unsupported; explicit accepted All Devices/raw-USB fallback; vary required/presence/hotplug/interfaces | No fallback: required export fails. Accepted fallback replaces only enforcement scope; every original requirement remains. Presence-required still blocks without the original matching authorized device; required hotplug cannot become startup-only. Raw USB cannot replace hidraw; portal-to-direct substitution rejects. A broad grant may expose excluded devices: report it as broader, never filtered. User denial does not trigger regrant. |
| USB06 | USB portal mode with/without qualified identity/Wine bridge, known blanket denial/unknown authorization, matching presence and later per-device consent | Required readiness checks backend/bridge before launch without acquiring a device. Known blanket denial blocks; unknown authorization stays pending. Presence-required checks matching visible hardware, not pre-approved per-device consent. With integration ready, later allow/deny/cancel returns native operation outcomes and only approved handles are acquired/released. No retroactive launch refusal, automatic regrant or metadata-only success. |

## Desktop, forwarding and services

| ID | Tier and scenario | Required assertion |
| --- | --- | --- |
| UX01 | B: normal window on selected qualified backend; input, resize, DPI, close/reopen | Usable window without forced Wine virtual desktop. This does not certify graceful application behavior after every optional denial. |
| UX02 | Q: desktop/MIME/CLI file forwarding, save-as, managed AppImage movement/update | Only approved file/parent/document-portal scope; new scope requires approval; no hidden parent/home grant or stolen default association. Managed route remains valid. |
| UX03 | Q: GPU enabled/denied; representative rendering | Qualified driver/runtime path actually works; device-node presence alone is insufficient. |
| SVC01 | Q: broad audio allowed/denied | Actual playback/capture scope matches the native connection. Narrow playback-only/capture-only modes remain unsupported until separately enforced. |
| SVC02 | Q: named D-Bus talk/own access, with/without the network grant and NET04 fixtures | Configured connection allows only declared names; no entire filesystem-bus substitute. Without another grant, unrelated calls fail. With networking, report reachable abstract routes as part of the union; do not claim global named-service or host-command isolation. Unresolved stronger denial conflicts refuse launch. |
| SVC03 | Q: each claimed printing/smart-card/authentication-agent integration allowed/denied | Its documented native service scope and authorization are correct; no arbitrary socket mount substituted. |
| SVC04 | Q: required portal backend/bridge missing or ready; later native allow/deny/cancel, omitted optional integration and cross-install identity attempt | Missing readiness blocks launch; ready integration launches without a resource prompt. Later native denial/cancellation is an operation result, not retroactive launch failure. Omission disables Cage integration without claiming all native portal methods are unreachable. Observe native persistence/revocation and interface-specific resource consent; no generic lease. Self-declared app ID cannot reuse another installation's grant. |

## Policy, state and trust foundation

| ID | Scenario | Required assertion |
| --- | --- | --- |
| POL01 | Deny required/optional preflight capability, including admin constraints; separately cancel a later portal operation | Required preflight denial refuses before payload/prefix mutation; optional omits/reports and launches if the remaining boundary is enforceable. Check the union for defeating grants. Later native resource cancellation does not become a preflight denial. No per-action interception, blanket portal API-disable claim or promise that arbitrary Windows code degrades gracefully. |
| POL02 | Native Flatseal/Flatpak override or Cage local decision; revoke while resource handles remain open | Respect effective native grants; no competing store or startup overwrite. Report actual close/restart/session-stop timing and verify denial at that boundary; no universal immediate-FD revocation claim. |
| POL03 | Update broadens permissions; decline; roll back after revocation | No new grant without acceptance; retained package remains recoverable; rollback does not resurrect grants. |
| ST01 | Fresh state, settings, relaunch and concurrent-launch attempt | Private stable state; immutable package retained; existing concurrency guard prevents competing Wine-server writes. |
| ST03 | Interrupt initialization or generation switch | Atomic recovery; prior usable state and incomplete candidates retained and correctly identified. |
| ST04 | Policy-only recipe change, native override and local binding change with identical state-compatible inputs; also legacy whole-plan adoption, real runtime update and rollback | Policy-only transition preserves active prefix, generation identity, settings and recovery generations without reseed/copy/migration or prefix writes solely to adopt policy. Changed source manifest/artifact digests remain verified. Unknown legacy provenance refuses adoption while retaining data. Actual state-affecting changes use existing qualified migration; rollback keeps current denials. |
| TR01 | Import/run AppImage through host Cage, desktop/MIME and CLI; compare direct execution/raw OCI launch and missing sandbox tools | Every managed route confines before artifact code; import never executes artifact extraction/AppRun. Missing host Cage/Bubblewrap/user namespaces refuses the managed route; direct AppImage/raw engine execution has no managed enforcement result. FUSE is not inferred from extraction success. |
| TR02 | Replaced import bytes, unsafe archive entries, mismatched contract/deployment, legitimate artifact or host Cage update interrupted | Unverified bytes never execute or mutate app state. Trusted extraction has bounds and safe paths. Authorized updates keep atomic registration and recovery; artifact cannot update the trusted host launcher/records. |
| TR04 | Child probes, plugin/self-updater, external policy/launcher modification attempt | Fixed boundary inherited; direct policy/launcher writes and ungranted direct host execution routes denied. Distinguish mutable app contents from seed identity. X11 and explicitly shared network service effects remain within their documented broad scopes; no blanket host-command isolation claim. |
| TR05 | Probe fixed mount/PID/proc/IPC/user boundary, host canary process, privilege elevation, namespace re-entry, inherited FDs and host controlling terminal | No host process/root/proc/namespace or descriptor escape, host signalling/inspection, privilege gain, or unintended shared IPC. Controlled stdio/acquired resources only; exact syscall/security-policy identities retained. Network namespace shared only with its explicit grant. Failed required baseline refuses execution; no extra recipe switches or assumption that engine/Bubblewrap defaults suffice. |

## Additional lifecycle and application qualification

| ID | Tier and scenario | Required assertion |
| --- | --- | --- |
| ST05 | Q: uninstall one of two apps needing a host device rule; include a modified rule | Shared need preserved; modified rule retained for review; user state/recovery retained by default. Installing rules authorizes the host user, not just the app. |
| ST06 | Q: explicit stopped-state cross-format transfer with matching/mismatching provenance | Only compatible import with explicit consent and new local bindings succeeds; source remains recoverable; no concurrent writable-prefix sharing. |
| APP01 | App: MyHarmony rendering/login and optional denial of files/USB in a variant that permits omission | Observe actual usable/degraded behavior, not a generic permission promise. External service failure is separate from access denial; an HTTP 403 cannot count as successful login. |
| APP02 | App: dedicated Harmony model detection, identical devices, hotplug, recovery identity and real sync | Preserve settings/recovery, confirm the app's actual selected target and successful operation per tested model/firmware. Synthetic USB reenumeration or generic fixtures cannot qualify physical sync or every Harmony model. |

## Target evidence and release gates

OCI retains image/deployment digests and actual engine configuration, including
mounts, namespaces, device controls, groups and LSM outcomes. Flatpak retains
installed ref/commit, native metadata, overrides and portal decisions; claimed
Flatseal visibility requires an observed supported UI version. AppImage retains
host Cage/Bubblewrap/extractor versions, imported digest, extraction receipt,
actual confinement plan and the verified managed desktop/CLI registration.

1. Design schema/examples/links pass structural checks; production v0 remains
   unchanged. Design checks reject unsupported v1; implementation checks require
   correct v1 support without relaxing v0.
2. Each B capability passes positive and negative cases on all three selected
   tuples, including fixed baseline, broad native networking, state/policy
   separation, binding replacement and managed pre-execution trust. Include at
   least one common local x86_64 host matrix supporting all three formats.
3. Each Q capability separately passes its applicable shared/composition cases
   across the formats claimed. Unsupported and missing prerequisites only pass
   refusal cases. F/X remain unavailable or explicit broader compatibility results.
4. MyHarmony completion requires APP01/APP02 and its online/device capabilities
   across all three formats. Publish capability/model-level gaps; neither a B
   release, package build nor broad fallback passes a failed narrow-access test.

IDs of merged cases are retired rather than renumbered. Host-matrix execution is
part of every case; it no longer has duplicate standalone ENV smoke tests. App
behavior, permission enforcement and structural design validation stay distinct.

## Final authority/runtime cases

| ID | Scenario | Required assertion |
| --- | --- | --- |
| AUTH01 | Same app ID with a different key, alternate cache or second Flatpak ref/installation | Refuse before deployment/state access; canonical trust pin is shared across formats; no grant/data inheritance |
| AUTH02 | Untracked native data/ref, verified explicit adoption and fresh ID | Unknown provenance retains all data and refuses; exact verified adoption is explicit; fresh ID has independent authority |
| TR06 | Relocate private-runtime source/staging and tamper ELF slot, closure or transformation | Managed materialization uses fixed namespace paths, verifies source/transformation and exposes only read-only runtime; legacy behavior unchanged |
| ST07 | Two permission-only releases share a compatibility identity, then rollback/crash | Exact release pointers remain unambiguous; active prefix/generations retained and current revocations respected |
| APP03 | Broad MyHarmony compatibility recipe on all three adapters | Same declared All Devices/network scope; real Wine hotplug and model-specific sync need their own positive evidence; strict fixture remains unsupported |
