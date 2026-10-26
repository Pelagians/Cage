# Proposed Cage recipe permission schema

Status: `cage.app/v1` parsing/normalization and the initial capability subset are
implemented. The companion JSON Schema validates the projection containing
`schemaVersion`, `id`, `execution` and `permissions`; other application fields
reuse existing validators with explicit v1 adaptations. Export plans accept the
online X11/All Devices candidate and the pinned Wine 11 x86_64 native Wayland
candidate; that does not establish runtime qualification. See [Wayland](wayland.md).
The strict selected-USB fixture remains a required-unsupported negative case.

## Recipe envelope

| Field | Type and rule | Meaning |
| --- | --- | --- |
| `schemaVersion` | Exact `cage.app/v1` | New contract; v0 keeps existing behavior |
| `id` | Required reverse-DNS identifier | Stable application locator across formats; not proof of publisher authority |
| `execution` | Required object | Environment, selected targets and explicit device fallbacks; managed v1 always enforces the fixed baseline |
| `permissions` | Required object with `requests` array | Publisher defaults and functional requirements |
| Existing fields | Existing name/version/runtime/sources/modules/launch/desktop/etc. | Reuse current application pipeline; do not duplicate module schemas here |

For a desktop recipe, existing `desktop.id` must equal `id`. Name, version,
architecture, artifact digest and publisher trust remain distinct. Real signer
verification and installation origin establish trust; a publisher name or key
string inside an untrusted recipe does not authorize reuse of prior grants.

`runtime.network` is forbidden in v1 to avoid competing runtime intent. A network
request grants the native shared host-network scope defined below; absence means
no host/external networking. There is no network `mode` field. Build networking
remains under `build.network`. Migration maps v0 `none` to absence and `host` to
the network request. V0 `bridge` needs explicit approval of the broader host
scope or stays on v0; it is not automatically equivalent. Record the origin and
review the full IP/abstract-socket exposure before use. A v0 recipe with both
old and proposed fields is rejected. Legacy CLI network overrides become
explicit local decisions in a v1 launch record.

Existing `desktop.documentsDirectory` remains metadata for legacy integration;
in v1 it creates no implicit host grant. A corresponding filesystem request is
required to expose that directory. Existing output `exports` retains its current
meaning; it is not reused for exporter policy. A resource/output overlap must be
resolved explicitly without duplicate mounts or silent widening.

## Execution fields

| Field | Values and default | Contract |
| --- | --- | --- |
| `environment` | `local-desktop`, `headless`, `remote-session`; required | The machine/session topology being qualified |
| `targets` | Nonempty unique list of `oci`, `flatpak`, `appimage` | Targets requested for this application |
| `fallbacks` | List; default empty | Exact target/request substitutions; no wildcard fallbacks |

V1 managed execution always enforces the fixed baseline in the proposal. The
removed `execution.isolation` field is rejected, including its former `required`
value. There is no recipe-level ordinary-process fallback. Production v0's
AppImage `--allow-host-access` path remains a separate legacy operation and gets
no v1 parity result. A broad declared resource grant is still enforced execution;
it does not permit ignoring the remaining filesystem/process/device boundary.

A fallback contains `target`, `request` (an existing permission ID), and `grant`
(an object containing only `kind: device-class` and `class: all|usb`). The first
schema deliberately supports only device-class substitutions; filesystem or
network fallback languages need their own future design.

A fallback is a publisher-proposed alternative, not user authorization. It must
appear in the export/install permission difference and be accepted through the
native installation flow or an explicit recorded operator action. Only one
fallback may address a given target/request pair. The target must be selected,
and the request must be a USB request with `access: direct`. Portal-to-direct
substitution would change the consent/integration mechanism and is outside this
fallback model. The replacement must cover the required host
interfaces; raw USB cannot replace a required hidraw path, and unrelated device
classes are not valid substitutes. ID, reason, requirement and host-authorization
needs survive the substitution. The original request remains the functional
requirement; only its enforcement grant is replaced. Normalize the original
request before evaluating a fallback, using these rules:

| Original component | After substitution |
| --- | --- |
| ID, reason, `required` | Unchanged; denial still follows the same launch rule |
| `presence`, `hotplug`, `interfaces` | Unchanged; validate against the original matching resource and required host interfaces |
| `allow`, `exclude`, local serial binding | Retained for presence/availability checks; no longer an access restriction under the broader grant |
| Host authorization, user denial, admin ceiling | Still apply; substitution cannot bypass them |
| Effective access scope | The broader class, reported and accepted as such |

A fallback adds no defaults of its own. It cannot drop a presence or hotplug
requirement, turn raw USB into hidraw, or silently switch direct access to a
portal. An unavailable resource probe yields unknown/unsupported, not ready.
A denied required request is not eligible for automatic broader regranting.
A replacement is never combined with the original narrow selector and
represented as filtered All Devices. Broad access alone does not prove that
the original device is present or that Wine can use it.

For example, this addition explicitly permits a broader Flatpak compatibility
export of the MyHarmony example:

```yaml
execution:
  environment: local-desktop
  targets: [oci, flatpak, appimage]
  fallbacks:
    - target: flatpak
      request: harmony-usb
      grant:
        kind: device-class
        class: all
```

The exact requested/effective scopes remain in the result. This compatibility
export is not a passing strict selected-device parity result.

## Permission request model

Each request has a unique `id`, a discriminating `kind`, a single-line `reason`
(maximum 240 characters), and optional `required` (default false). Listing a
request defines a publisher default; it is not an irrevocable grant. `required`
has one meaning: it is a launch prerequisite. There is no per-feature dependency
graph or interception of arbitrary operations inside a Windows application.

| Resolved condition | Launcher behavior |
| --- | --- |
| Required request denied, unsupported, or known unavailable | Refuse launch before payload execution or prefix mutation; explain the request and remedy |
| Optional request denied, unsupported, or unavailable | Omit its grant, report the condition, and permit launch if the remaining boundary can be enforced |
| Enforcement of a denial/baseline is unavailable | Refuse qualified launch even if the affected positive request was optional |
| Required USB access is enforceable; device absent with `presence: optional` | Permit launch and report waiting for device; host authorization remains pending |
| USB `presence: required` without a matching visible device | Refuse launch; this setting requires `required: true`. Direct access also needs host authorization; portal device consent may still be pending |
| Required portal integration or portal USB backend/bridge unavailable or blanket access known denied | Refuse launch; check integration readiness without prompting for a file/device |
| Integration ready; later file/device request denied or cancelled | Return the native operation result; do not retroactively apply a before-launch refusal or repair/regrant access |

Unknown kinds and malformed requests always fail validation, including optional
ones. Optional omission is available only for a well-formed known capability.
The launcher does not promise that the application handles an omitted feature
gracefully; that behavior needs a separate application integration result. A user
denial never authorizes regranting or invocation of a broader fallback.

For `portal` and USB `access: portal`, required means the native interface,
identity and participating Wine/library bridge must be available at launch.
A known blanket portal denial blocks required integration; unknown native
authorization remains pending rather than being treated as pre-approved. This
does not require pre-approving a particular file,
device or future operation. The generic denial rows concern preflight capability
decisions; operation-specific native consent follows the last two rows instead.
Readiness is not evidence of resource acquisition. Never open a chooser or acquire
a device merely to make a launch preflight pass.

Required describes the need for an access capability, not the physical presence
of its resource. A required USB capability can have `presence: optional` and
start in a waiting-for-device state. Unsupported enforcement or a known user
denial cannot be reported as waiting for hardware. Host authorization that can
only be probed after connection remains pending, not verified.

Normalization materializes the documented defaults and sorts set-valued fields
and requests by stable identity for hashing. Ordered build modules and launch
arguments retain order. Arrays are sets where stated; IDs are stable references.
Unknown properties, unknown kinds, duplicate IDs, malformed strings and ambiguous
legacy combinations are errors. General deny precedence is resolved against native effective grants;
there is no recipe-level arbitrary deny expression language in this version.

A uniform list allows several folders, USB families and service connections,
with the same ID-based local override and evidence rules. A future UI can group
requests into Flatseal-like categories without adding boolean shorthand syntax
or a second permission model.

| Kind | Required kind-specific fields | Optional fields and defaults |
| --- | --- | --- |
| `filesystem` | `location`, `access: read-only|read-write` | `create: false`, `wineDrive`; missing behavior follows `required` |
| `network` | No additional fields | Shared host-network namespace, including abstract Unix sockets; no mode/filter fields |
| `display` | `backend: x11|wayland` | Exactly one per recipe initially; must match qualified Wine graphics |
| `device-class` | `class: gpu|usb|input|all|kvm|shm` | `hotplug: required|startup-only` (startup-only for every class); each mapping is separately qualified |
| `usb` | `access: direct|portal`, `interfaces`, `allow` match list | `exclude: []`, `presence: optional|required` (optional), `hotplug: required|startup-only` (required) |
| `audio` | `access: playback-and-capture|playback|capture` | Narrow modes remain F until enforced |
| `dbus` | `bus: session|system`, `talk` and/or `own` nonempty name lists | Both lists default empty; at least one must be nonempty |
| `host-service` | `service: printing|smart-card|ssh-agent|gpg-agent` | Each is qualified independently; no arbitrary socket path |
| `portal` | `interface: file-chooser|open-uri|print|camera|notifications` | Integration readiness; resource consent happens natively at operation time; no generic lifetime field |

A schema-valid advanced request can produce unsupported until its implementation
is qualified. Structural validity is not a support claim. GPU/device nodes,
resource limits, environment variables and authentication-agent access are not
interchangeable: `launch.env` stays configuration, and CPU/memory budgets stay
separate future resource policy rather than permission grants.

## Filesystem locations and Windows presentation

`location` has a `base` and optional `path`. Bases are `home`, `xdg-desktop`,
`xdg-documents`, `xdg-download`, `xdg-music`, `xdg-pictures`, `xdg-videos`,
`xdg-config`, `xdg-cache`, `xdg-data`, or `absolute`.

For a symbolic base, omitted `path` means that whole location. A provided path
must be a relative POSIX path with no empty, dot or parent components. For an
absolute base, `path` is required and must be absolute. No shell, environment or
command expansion is allowed. Unicode and spaces are valid; control characters
are not. Absolute producer/user paths are marked nonportable in the plan.

The launcher resolves symbolic paths on the execution host. Flatpak receives
native XDG grants, while OCI and the AppImage sandbox bind resolved paths.
Windows drive aliases point into the namespace actually made available by the
backend. Drive aliases do not create access. Duplicate/reserved C and Z aliases
are rejected; case is normalized. A request for a missing read-only location must
not create it. `create: true` requires read-write, safe user-owned parent traversal
and the approved creation scope. Existing directory owners/modes are retained.

A missing optional path is omitted; a required missing path blocks launch unless
authorized creation succeeds. `create: true` is attempted only after the grant
is accepted. The removed `missing` field is rejected: it would duplicate or
contradict `required`. No missing path becomes a temporary unrelated folder.
Broad or overlapping bindings are checked against protected package, state,
policy and runtime paths. Generic filesystem grants cannot substitute for device
or service requests. Symlinks, mount changes and resource replacement must be
resolved safely by the backend; unrepresentable restrictions error. Preventing a
namespace escape does not mean preventing every host-side race for writable
content intentionally shared with other processes.
Bindings authorize a path scope, as native filesystem permissions do, not a
permanent inode/volume identity. Re-resolve safely on launch; replacement content
within that approved path alone is not a new grant. Reject traversal/protected
scope conflicts; no cross-format inode-tracking database is introduced.

Local filesystem bindings replace the publisher location for that request.
Resolve them before final rule emission, keeping access/create/drive settings.
For Flatpak the explicit stopped-app change is native-first:

1. Preview the exact old-path nofilesystem/new-path filesystem delta and effective
   union, including independent user/other-request grants. Preview writes nothing.
2. The operator applies changes through Flatseal or the native CLI. Cage never
   writes or rolls back native overrides. A broad home denial does not remove a
   more specific manifest path; the exact old path must be suppressed.
3. Rerun bind: verify native scope and app/trust identity, take Cage's lifecycle
   lock, re-read the native snapshot and atomically adopt only the binding receipt.
   A changed snapshot or unresolved old access refuses exact adoption. Preserve
   independent grants; never label a two-folder result a one-folder grant.
4. Re-read after adoption and verify actual launch scope before payload code.
   Detected drift requests reinspection/reconciliation; it never restores old
   native grants. The receipt is a recoverable binding decision, not a second
   permission database or a transaction spanning independent native writers.

OCI/AppImage generate the next mount plan from the same resolved bindings.
[Flatpak filesystem override semantics](https://docs.flatpak.org/en/latest/flatpak-command-reference.html).

## USB selectors and direct access

A USB match has optional `vendor`, `product`, `productRange`, `class`, `subclass`
and `serial` fields. At least one usable identity constraint is required.
Vendor/product IDs are four lowercase hex digits; class/subclass are two.
A product or range requires a vendor. Product and range are mutually exclusive;
a range contains `first` and `last`, with first not greater than last. Subclass
requires class. Serial constraints require another usable identity constraint.
No selector is authorization to trust the device's firmware or strings.

Fields within a match are ANDed. Matches in `allow` are ORed, then `exclude`
subtracts matching devices. An adapter must reject a selector it cannot enforce.
A range can expand to bounded individual native queries without changing scope;
large expansions require explicit resource limits. Serial filtering that needs
unapproved device I/O cannot be claimed without a qualified acquisition path.

`interfaces` is a nonempty set of `usb` and/or `hidraw`. These identify host access
paths, not Windows API names. Portal mode requires exactly `[usb]`: a Wine HID
bridge may translate Windows HID calls to the acquired USB handle, but ordinary
hidraw enumeration does not consume that handle automatically.

A broad device-class request overlapping a selected USB request can defeat its
selector. Such mixtures are conflicts for a strict narrow contract; explicit
broader fallback resolution is represented as a substitution. All Devices does
not imply shared host POSIX shared memory, root capabilities or a change to host
ACLs. `hotplug` describes the availability guarantee, not an extra device
selector: startup-only does not promise that later devices are denied by a broad
class grant. A required hotplug request cannot silently become startup-only.
All Devices and raw USB are Q capabilities, including startup-only use, until
their device scope, host authorization and requested event behavior are qualified.
Static node mappings do not establish hotplug. Each dynamic implementation must
specify how new nodes, device controls, enumeration metadata and notifications
reach the sandbox without sharing unrelated host services or disabling policy.

Firmware/recovery identities belong in the same family's explicit allow list.
Device disappearance, reconnect, changed node numbers, several identical devices
and exclusive use all require behavioral tests. Physical topology and serials
are private host bindings, not portable package identity or default log content.

## Network and service scope

At most one network request is accepted. Absence denies host/external IP and
host abstract Unix socket access; private in-sandbox loopback may remain available
for Wine/internal services and is recorded in the baseline. A `kind: network`
request explicitly grants shared host-network namespace scope, including host
loopback, reachable LAN/Internet services, inbound socket binding subject to host
policy, and the host abstract Unix socket namespace. Authorization at an endpoint
still applies. There is no internet-only, domain, port or private-address filter.

The common native mapping is OCI's host network option, Flatpak's native network
sharing, and Bubblewrap retaining the host network namespace while isolating the
other baseline namespaces. This is one broad grant with no `mode` or new profile
selector. It avoids requiring a custom IP/Unix-socket filtering layer for basic
networking. A manifest/install report must disclose abstract-socket exposure even
if no host abstract service currently listens. Later services are in that granted
scope; a clean socket inventory cannot make it narrower.

Other filesystem sockets, mounts and host commands are not granted by networking.
A host service reachable via an allowed IP/abstract endpoint may nevertheless
have substantial authority, just as an allowed display protocol does. Report this
scope; do not promise global host-command/service isolation for an online session.
Named D-Bus rules filter their configured bus connection but cannot impose a
global named-service restriction if networking offers another abstract route.
Evaluate access as the union of all grants. An explicit user/admin denial which
another grant defeats is a conflict requiring a resolved policy, never a false
denied result. Decline the network grant to obtain the offline baseline; a
future isolated-IP/strict-service-denial capability requires its own design and
is unsupported here. No implicit stricter/broader network fallback is added.

LAN discovery and inbound application behavior still need application/host
qualification; the grant does not repair firewalls or service availability.
[Flatpak network/abstract socket interaction](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

Network absent also requires controlled host filesystem sockets and service
connections; an undeclared proxy or host-command service must not bypass a
claimed direct-access denial. A native portal/delegated action allowed by the
resolved baseline and native authorization, such as opening a URI in a host
browser, may itself use the network. Report that channel even if the recipe did
not declare a Cage portal integration; omitting the declaration is not a native
API-disable guarantee. Do not label the session completely offline or claim no
host-network effects. General network access does not
include a port allowlist guarantee; inbound filtering is a later capability.
Fixed runtime inputs such as CA certificates are inventoried baseline resources.
Endpoint availability, DNS failure, HTTP 403 and authentication failure are
reported separately from permission/enforcement failure.

D-Bus names follow well-known bus name grammar; only a final `.*` namespace
wildcard is allowed. Native/proxy filtering must preserve the declared names on
that connection. Entire filesystem-bus exposure is not a named-service fallback.
Combined with networking, the report also records the broader abstract endpoint
scope above; a successful filtered call test does not prove global bus isolation.

Portals declare an integration requirement, not a uniform lease. The adapter
reports each native interface's consent, persistence and actual revocation
behavior. File chooser document grants may survive sessions; OpenURI/print
delegate an operation; notifications have their own add/remove lifecycle; camera
uses its native authorization and stream access. A declaration alone implements
none of these in Wine. Do not promise immediate revocation of open descriptors
or undoing a completed delegated action. Any additional lifetime restriction
needs a later interface-specific design and qualification, not a generic enum.
Native portal discovery/consent methods belong to the controlled baseline bus
surface; not every interface has a static Flatseal permission switch. Omitting
an optional `portal` request disables Cage's integration, not the platform's
native consent API. Do not report that omission as kernel-level denial of every
portal call. Resources selected through a portal remain protected by native
consent; backend readiness never constitutes consent to a selected file/device.
Specific native blanket denials, where supported, remain authoritative. Record
request success, cancellation and failure at operation time without changing the
launch prerequisite into a per-action dependency system.
[FileChooser persistence](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.FileChooser.html),
[Notification interface](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Notification.html),
[Native request cancellation](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Request.html).

## Local decisions and effective policy

The local example is a design for binding and decision records, not an additional
Flatpak permission database. For Flatpak, native overrides and portal stores are
authoritative for grants; Cage stores only resource bindings and consent receipts
needed for its own integration. OCI and AppImage use existing Cage local metadata
with safe atomic updates and ownership checks.

Resolution proceeds in this order:

1. Validate the recipe, resolve runtime ownership, and inventory the baseline.
2. Read native grants and current decisions; resolve local resource bindings as
   replacements before final rules are emitted. A launch never silently performs
   a binding-change transaction or resets user overrides.
3. Compile the resolved requests for the target/environment, including the union
   of network, device, service and baseline access. Evaluate a listed device
   fallback only for an unavailable exact mapping and subject to current denial.
4. Apply host/admin constraints and user decisions; no decision can exceed an
   enforcing administrator ceiling or host authorization. Detect conflicting
   overlapping grants before reporting an effective denial.
5. On export/explicit setup, emit and verify the final native grant delta or
   deployment. Ordinary Flatpak launch verifies installed configuration without
   rewriting overrides; a needed binding/setup delta requires the explicit
   transaction above. OCI/AppImage form their next launch configuration from
   the resolved policy. Reject unresolved transactions or unaccepted mismatches.
6. Preflight host capabilities and enforce before application code starts.

Apply the launch table above after resolving each well-formed request. A
required unsupported request blocks its target export; a known optional
unsupported request can be omitted with an explicit plan result and no grant.
Package creation does not waive launch-time host prerequisites.

A recipe requirement cannot override a user denial. A user may deliberately grant
more through native controls; the next effective report must show that scope.
If resource scope exceeds the request, require explicit acceptance of that
broader resource contract or refuse qualified launch. Acceptance cannot waive
the fixed process/privilege/integrity baseline or a current explicit denial:
an unresolved conflict refuses the managed launch. There is no accepted
unenforced v1 outcome. Never reset native overrides at launch to make a test pass.
Missing bindings, waiting hardware, host setup and an unsupported backend are
different states.

A canonical per-user/app-ID authority pin in the existing release ledger binds
all formats to one verified publisher key. Artifact cache selection cannot create
another authority namespace. One managed Flatpak ref/installation is allowed per
app ID because native data and portal grants are app-ID scoped. Different
publishers must use fresh IDs; same-ID takeover is unsupported. Existing native
refs/data without matching provenance refuse adoption and retain everything.
Verified adoption is explicit and preserves prior grants/state until its checks
pass. Cross-format state import remains explicit and stopped, never live sharing.

## Permission changes and existing application state

Keep exact active/previous release digests in the installation ledger, separately
from compatibility identity: several policy-only releases may share compatible
state. Never select a release by requiring its compatibility key to be unique.
Version new state/release records instead of reinterpreting legacy identities.

Keep three identities distinct: application/state compatibility, publisher
permission contract, and host effective policy. Artifact/deployment digests bind
all of them for integrity; an integrity change alone is not a prefix migration.

The current desktop state helper hashes the complete export plan, including the
source manifest digest. Simply adding permission metadata would therefore make
a permissions-only recipe change look like a state mismatch. V1 needs an
explicit compatibility projection and a versioned adoption path before launch:

| Change | Required transition |
| --- | --- |
| Publisher permissions, fallback, consent, native override or local resource binding only | Recompile/reapprove access; retain the active prefix, generation identity, settings and recovery generations; do not reseed, copy, migrate or rewrite the prefix merely to adopt policy |
| Seed, runtime/ABI, application installation or other state-affecting execution inputs | Existing separately qualified update/migration rules; retain recovery data |
| Existing whole-plan-hash state record | Explicit verified adoption using the original package/plan and unchanged state-compatible inputs; unknown provenance refuses adoption and retains all data |

The projection retains qualified seed/runtime identity, application ID and trust
domain, architecture, launch/compatibility inputs and state/update profile.
Only declared permission-related inputs are excluded; never bypass an existing
mismatch by ignoring all changed manifest fields. Full source/artifact digests
remain verified in integrity receipts. Policy compilation must not alter the
prepared seed. Drive aliases are launch presentation within the granted
namespace, not authority to repair or reseed CFW-owned state.

Policy-only adoption is atomic outside the prefix and under the existing lifecycle
lock. A running instance keeps its recorded effective policy until the reported
restart/close boundary. A failed change leaves state usable with its retained
package; the next launch still applies current revocations and user decisions.
Rollback restores package/state according to existing rules, never old grants.
[Current whole-plan identity](../../../runtime/desktop_launch.py),
[Current export-plan inputs](../../../artifact/desktop.py).

## Result metadata

A proposed `cage.capability-plan/v1` record accompanies existing graph/export
metadata. It contains application/runtime/artifact identity, normalized request
digest, target/environment and adapter version, host prerequisites and baseline
resource inventory. Each request records requested scope, resolved scope,
mechanism, selected fallback, functional requirement, enforcement status,
resource availability, host setup and revocation timing.

Enforcement values are `exact`, `broader-accepted`, `unsupported` and `denied`.
There is no managed-v1 `not-enforced` success. For a portal declaration, exact
describes qualified native consent/integration behavior, not a pre-granted
resource or an ability to disable every native portal method. Availability
values are `ready`, `missing`, `waiting-for-device`,
`host-setup-required`, `service-unavailable` and `unknown`. These are independent:
an exact sandbox rule can exist while the remote is unplugged. A plan is not
runtime evidence; separate receipts state what was actually tested.
Portal preflight availability describes the integration; operation receipts
record resource acquisition or cancellation separately. Unknown authorization
must never be reported as an acquired file/device grant.

Static export plans carry requirements, not frozen assertions about a future
host. Host-specific effective reports reference the contract and deployment
digests. Evidence omits document contents, credentials and raw device serials.
It identifies which launch path established enforcement and whether additional
human decisions are needed. Unmanaged launch cannot acquire an exact badge by
reading an embedded policy file.

## Validation outside JSON Schema

The JSON Schema checks shapes, enums and local constraints. The prospective
compiler must additionally check unique IDs and singleton resources, path safety,
hex range ordering and expansion quotas, bus grammar, drive aliases, selector
compatibility, administrator ceilings, protected-resource conflicts, fallback
references, publisher trust, platform versions and the actual effective scope.

Do not implement a permissive v1 parser that treats unrecognized fields as v0.
Migration is explicit and reviewable. Existing CFW/runtime locks, ordered module
semantics, BYO source policies, lifecycle proofs and recovery records remain
owned by their current components.

## Managed AppImage preparation

Use trusted host extraction and the existing private ELF materializer with an
optional namespace root. Managed roots are /app and /run/cage/native. Verify
source hashes and the reserved interpreter slot, permit only that declared ELF
transformation, verify the resulting tree, and bind both trees read-only. Do not
execute AppRun, bundled Python or extraction runtimes before confinement. The
closure manifest and materializer ABI enter stable compatibility identity; host
temporary paths do not. Legacy relocation/materialization remains unchanged.
