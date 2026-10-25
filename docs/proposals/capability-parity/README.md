# Cage capability parity design

Status: v1 source implementation, qualification pending, 24 October 2026. The explicit parser,
shared planner, managed adapters and trust/state records are implemented. The
v0 recipe keeps its existing behavior. Runtime, desktop and physical hardware
qualification remain separate release gates; see [implementation status](implementation-status.md).

Cage should export one application contract to OCI, Flatpak, and AppImage, with
comparable application behavior and access controls on qualified Linux hosts.
A successful package build establishes neither behavioral nor enforcement
parity. A capability remains unavailable until its backend and shared tests
establish its stated semantics.

The design extends the existing recipe, execution graph, verified bundle,
export plan, and lifecycle helpers. It introduces no replacement installer
pipeline, prepared prefix, permission database for Flatpak, or mandatory
privileged daemon.

## Design artifacts

- [Proposed recipe schema](recipe-schema.md): fields, normalization, policy
  resolution, host bindings, migrations, and examples.
- [New field JSON Schema](recipe-extension.schema.json): structural validation
  of the proposed v1 identity, execution, and permission fields only. Existing
  application fields reuse existing validators with explicit v1 adaptations.
  This is not a complete standalone application schema or a production parser.
- [Acceptance tests](acceptance-tests.md): shared scenarios, target assertions,
  evidence requirements, and release gates. These are specifications, not an
  complete runtime test suite or passed results. Source tests and shared probes now accompany these specifications.
- [MyHarmony example](examples/myharmony.cage.yaml): strict negative fixture derived from
  the checked-in source recipe. Its selected USB request is recognized and
  unsupported; the [broad candidate](examples/myharmony-compat.cage.yaml) uses
  All Devices consistently on the three targets.
- [All Devices example](examples/all-devices.contract.yaml): proposed field
  projection showing the broad device request; not a runnable application.
- [Local binding example](examples/local-bindings.yaml): prospective local
  configuration, outside the published recipe and Wine prefix.

## Parity definitions

Behavioral parity means the same supported operations produce equivalent user
results: opening files, saving, receiving device events, relaunching, and
recovering state. It does not require identical installation paths or identical
Linux runtime bytes.

Enforcement parity means grants and denials have the same documented scope.
For example, granting one folder must not expose its siblings on one target.
A broader accepted fallback can establish a compatibility result, but cannot
count as exact enforcement parity for the original narrow request.
Access is the union of declared grants: a broad network/device permission can
cover a route that another narrow rule does not. Reports must describe that
union and may not label an overlapping denial enforced.

Lifecycle parity means updates, permission changes, denial, rollback,
uninstallation, and explicit state transfer preserve the same user decisions
and recovery guarantees. It does not imply concurrent sharing of one prefix.

The first qualification environment is a local Linux desktop. Remote sessions,
headless execution, VM-backed engines, and Kubernetes are distinct environments;
passing local desktop tests does not qualify them automatically.

## Final implementation decisions

- One canonical user/app-ID publisher pin lives in the existing release ledger,
  independent of artifact caches. Formats share the pin; one managed Flatpak
  ref/installation is allowed per app ID. Different publishers need fresh IDs;
  untracked installations/data require explicit verified adoption, never reset.
- Flatpak folder changes are native-first. Cage previews the exact native delta,
  verifies the resulting effective scope, and atomically adopts only its own
  binding receipt. It never writes/restores native overrides, including during
  concurrent edits or recovery. There is no cross-store atomicity claim.
- The first functional MyHarmony candidate uses explicitly accepted All Devices
  on all three targets, with required hotplug, networking and normal X11 windows.
  The strict selected-USB example remains a negative fixture/future milestone.
- Managed AppImage execution reuses the existing private ELF materializer with
  a namespace-root option. Trusted host Cage verifies/transforms the runtime,
  then mounts the source at /app and prepared tree at /run/cage/native read-only
  before executing artifact code. Legacy behavior remains unchanged.
- State compatibility and exact active/previous release digests are separate.
  Permission-only releases can share state without ambiguous release selection
  or a prefix migration. Closure/materializer ABI identities remain protected.

## Current implementation boundary

Reviewed source baseline: `06bff7ad060946e1ac2941f807b197f33fa2306e`.
The following observations describe that source, not this proposal's goals.

| Area | Current Cage behavior | Design consequence |
| --- | --- | --- |
| Recipe | [v0 fields](../../../core/manifest/constants.py) are strict; no general permission field | Version the new contract; preserve existing v0 behavior |
| Flatpak | [Exporter](../../../artifact/flatpak.py) emits fixed offline, X11, IPC and application Documents access | Compile requests into native metadata instead of fixed grants |
| OCI | [Exporter](../../../artifact/oci.py) binds a container runtime; desktop-target bundles are rejected | Carry a deployment contract and qualify each runtime realization |
| Containers | [Launcher](../../../runtime/launcher.py) builds network and bind-mount arguments | Reuse this launch plan; a custom raw engine command is outside the parity claim |
| AppImage | [Exporter](../../../artifact/appimage.py) explicitly accepts ordinary host access | Enforced v1 needs a trusted host sandbox launcher; legacy ordinary execution remains distinct |
| Desktop build | [Validator](../../../artifact/desktop.py) permits a narrower module/runtime set than containers | Permission parity does not make CFW or Linux-state recipes portable |
| State | Managed desktop identity hashes the full export plan, including source manifest identity | Separate policy identity from state compatibility through explicit verified adoption; preserve existing recovery ownership |

## Execution and trust boundary

| Target | Contract that travels with the application | Enforcement owner | Qualification prerequisite |
| --- | --- | --- | --- |
| OCI | Image digest plus permission/deployment contract bound to that digest | Container engine and Cage's generated launch configuration | Rootless engine, OCI runtime, user mappings and host policies tested together |
| Flatpak | Native metadata plus the normalized Cage contract | Flatpak, native overrides and supported portals | Host Flatpak, portal backend and Wine integration meet the capability requirements |
| AppImage | AppImage digest plus normalized contract | Trusted host launcher entering a tested sandbox before artifact code runs | Compatible sandbox tools, kernel policy and trusted artifact inspection |

OCI image metadata does not establish host device mappings. Linux runtime
configuration contains the device and namespace settings that must accompany
an image. [OCI image configuration](https://github.com/opencontainers/image-spec/blob/main/config.md),
[OCI Linux configuration](https://github.com/opencontainers/runtime-spec/blob/main/config-linux.md).

The proposed managed AppImage path uses the host-installed Cage CLI, updated
through Cage's existing release/install process independently of the application.
No new daemon or independently distributed launcher product is required. Its
first sandbox backend is host-provided Bubblewrap with enabled user namespaces;
each supported host/tool version still needs qualification. This is a design
choice, not an implemented launch command.

The managed installation/launch flow is:

1. The user imports an AppImage into Cage. Host tools inspect and safely extract
   its SquashFS payload into a Cage-owned cache bound to the artifact digest;
   neither AppRun nor the artifact's extraction runtime executes. Pin the imported
   bytes against replacement; reject unsafe entries and apply extraction limits.
2. Cage verifies artifact/contract linkage and installation origin, shows the
   permission difference, and registers desktop/MIME actions with the absolute
   host Cage executable and installation identity. CLI launches use that same
   installation record; a new artifact cannot take over it by reusing an app ID.
3. Cage checks current grants and host prerequisites, prepares the namespace,
   and enters the verified payload only after confinement. Private state uses
   the existing application lifecycle boundary. The app opens a normal window.
4. Artifact replacement, movement and updates go through the managed import/update
   path with atomic registration, current consent and retained recovery records.
   Updating Cage rechecks backend compatibility before the next launch. Neither
   application code nor its updater can replace the host launcher or its records.

The first qualified path uses trusted host extraction; FUSE mounting is a later
separate path. Artifact-supplied `--appimage-extract` is not trusted extraction.
An AppRun script that voluntarily starts a sandbox does not establish this
boundary. Bundling Bubblewrap cannot enable a disabled kernel feature.
[Bubblewrap security model](https://github.com/containers/bubblewrap/blob/main/README.md).

Raw engine launches and ordinary direct AppImage execution can be supported
operationally, but must not inherit a Cage-managed enforcement badge. The host
operator remains able to change their own launch configuration. This design
protects the launch's declared boundary, not the host from its administrator.

## Capability matrix

Every cell below is a proposed mapping or qualification task, not a claim of
current Cage support. B identifies the first parity milestone, Q a separately
qualified integration, F a later capability, and X no faithful mapping through
the stated direct mechanism. B is the foundation: private state, folders,
network absence or explicitly broad native sharing, one normal-window backend,
and fixed isolation/lifecycle/trust rules. Devices and services are Q rather than
implicit baseline promises. They remain part of the three-target parity goal and
cannot be marked complete merely because a narrower foundation ships. Every tier
needs explicit host prerequisites and composition checks.
Test IDs refer to the acceptance document.

| ID and capability | OCI managed launch | Flatpak | AppImage enforced launch | Tier and tests |
| --- | --- | --- | --- | --- |
| C01 Private writable application state | Dedicated user-owned state volume | App-private data directory | Private XDG state directory | B; ST01, ST03 |
| C02 Read-only external folder | Bind mount read-only | Native filesystem read-only grant | Read-only sandbox binding | B; FS01, FS03 |
| C03 Writable external folder and atomic saves | Bind directory read-write | Native writable directory grant | Writable sandbox binding | B; FS02, FS04-FS05 |
| C04 Folder creation and absence | Explicit user-owned creation; no automatic chown | Native create behavior where equivalent | Trusted setup before binding | B; FS03-FS04 |
| C05 File-manager and command-line file forwarding | Resolve only approved file scope | Document forwarding or already granted path | Broker or narrowly scoped binding | Q; UX02 |
| C06 Direct IP network disabled | Isolated network namespace and controlled host sockets | Native unshared networking and controlled host sockets | Isolated network namespace and controlled host sockets | B; NET01 |
| C07 Native host-network access | Rootless engine host-network option | Native network sharing | Retain host network namespace while isolating other baseline namespaces | B; NET02, NET04; explicit IP/abstract-socket scope |
| C09 LAN discovery and inbound service behavior | App multicast/listening on the shared host network; no container port-publishing layer | App multicast/listening with native network sharing | App multicast/listening with host network retained | Q for actual application behavior; host firewall still applies; restricted port policy F; NET03 |
| C10 Normal X11 or Wayland window | Qualified display socket/auth integration | Native display permission | Qualified display socket/auth integration | B per selected backend; UX01 |
| C11 GPU acceleration | Qualified device and driver integration | Native DRI permission and graphics extensions | Qualified render nodes and host driver integration | Q; UX03 |
| C12 Broad audio playback and capture | Qualified audio service connection | Native audio socket | Qualified audio service connection | Q; SVC01 |
| C13 Playback only or capture only | Enforcing broker needed | Enforcing portal/service integration needed | Enforcing broker needed | F; SVC01 |
| C14 All Devices | Qualified device-only exposure; no privileged shortcut | Native All Devices metadata plus host authorization | Qualified broad device namespace | Q; DEV01-DEV02; startup-only does not imply hotplug |
| C15 All raw USB devices | Qualified USB exposure and engine device controls | Native USB devices metadata plus host authorization | Qualified USB device namespace | Q; DEV01-DEV02; hotplug requires separate positive evidence |
| C16 Input devices, KVM, shared memory | Specific qualified mappings | Corresponding native categories | Specific qualified mappings | Q independently for each class; DEV01 |
| C17 Selected USB via direct USB/hidraw paths | F: selected exposure plus qualified hotplug mediator | X: native raw-device grants do not filter by USB IDs; explicit broader fallback only | F: selected exposure plus qualified hotplug mediator | F or qualified compatibility fallback; USB01, USB02, USB04 |
| C18 Selected USB through a portal | Qualified identity and Wine/library bridge | Native USB queries plus qualified Wine/library bridge | Qualified identity and Wine/library bridge | Q; USB01, USB02, USB06 |
| C19 Named session/system D-Bus connection | Filtered proxy | Native named bus permissions | Filtered proxy | Q; SVC02; network sharing may expose an additional abstract route, so no global named-service isolation claim |
| C20 Printing, smart cards, authentication agents | Individually qualified service connections | Native sockets/portals as applicable | Individually qualified service connections | Q per service; SVC03 |
| C21 File chooser, URI, camera and other portals | Identity and runtime integration | Supported native portal plus runtime integration | Identity and runtime integration | Q per portal; SVC04 |
| C22 Update, rollback and uninstall behavior | Existing lifecycle plus separate policy decisions | Native package lifecycle plus Cage state handling | Existing integration plus trusted launcher | B; ST01, ST03-ST04, POL03; shared device rules separately Q in ST05 |
| C23 Cross-format state transfer | Verified export/import into stopped instance | Verified export/import into stopped instance | Verified export/import into stopped instance | Q; ST06 |
| C24 Isolated-IP/strict service denial, domain allowlists, arbitrary host commands, kernel drivers | Specialized future enforcement/integration | No automatic native general equivalent | Specialized future enforcement/integration | F; unsupported gate PL03; not required for basic networking |
| C25 Remote client files or USB | Explicit forwarding component required | Separate remote execution design | Separate remote execution design | F; unsupported/prerequisite gate PL03 |

Flatseal exposes filesystem grants, device classes and USB portal query controls
through Flatpak's native mechanisms. Cage must preserve native overrides rather
than maintaining a competing Flatpak grant store.
[Flatseal permission documentation](https://github.com/tchx84/Flatseal/blob/master/DOCUMENTATION.md).

Flatpak's All Devices category excludes its separately controlled shared-memory
category. Raw USB exposure and USB portal queries are different operations;
queries constrain portal enumeration, not direct device paths. Cage must enforce
host-version gates rather than relying on older hosts ignoring new metadata.
USB device/query support starts at Flatpak 1.15.11; conditional permissions
require 1.17. Host checks must also query the actual portal interface/backend.
[Flatpak command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html).

The USB portal returns descriptors for participating libraries and has limits
on immediate revocation. Merely adding metadata does not adapt Wine's existing
HID operations. [USB portal interface](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Usb.html).

## Baseline isolation and resource interactions

The baseline is fixed for managed v1; it is not another configurable permission
profile. Each qualified adapter must satisfy these observable requirements even
when its implementation differs:

| Area | Fixed requirement and shared probe |
| --- | --- |
| Mounts and runtime | Read-only verified package/runtime, private writable state and temporary files, minimal pseudo-devices, and only granted host paths. Inventory CA trust, locale/time-zone, DNS when online, fonts/graphics and controlled portal discovery/consent bus methods. No whole-home, host-root or policy-store mount by default. |
| Process/proc visibility | Private PID namespace and proc view; no host-process handles, host `/proc/PID/root` escape, ptrace/process-memory access or signalling of host control processes. A host canary process remains inaccessible; child processes stay in the boundary. |
| Other namespaces | Private mount, user/credential, IPC and UTS contexts. Host network namespace only with the explicit network request; otherwise private network/abstract sockets. Shared-memory/device grants do not implicitly share all host IPC. |
| Credentials and privilege | Rootless host execution, no host root identity, dropped capabilities and no_new_privs. Set-ID/file-capability payloads cannot raise privilege. No privileged engine mode, host namespace re-entry or silent LSM disabling. |
| Descriptors and session | Close inherited descriptors except controlled standard I/O and explicitly acquired resources. No inherited host directory/socket/namespace descriptor or controlling host terminal; establish a separate session/appropriate terminal protection. |
| Syscall policy | Use qualified native Flatpak/OCI policy and a host-supplied Bubblewrap filter where needed to meet the same host-boundary denials. Record exact filter/version identity; do not require identical filter bytes or indiscriminately disable Wine/browser sandboxing. Host mount/namespace and process-inspection escapes must fail. |

These are behavioral minima, not a claim that a finite probe suite proves every
possible escape impossible. Native defaults are reused but are not evidence by
themselves; failed baseline enforcement refuses the managed launch. The security
policy is part of adapter qualification, not new recipe fields.
[Flatpak baseline](https://docs.flatpak.org/en/latest/sandbox-permissions.html),
[Bubblewrap policy responsibilities](https://github.com/containers/bubblewrap/blob/main/README.md).

With the network grant, shared IP/abstract Unix endpoints are deliberately in
scope, including services started later. This native mapping is practical on all
three targets without a new networking daemon/proxy. It does not bypass endpoint
authentication, but can expose host services with substantial authority. The
effective report and installation consent must disclose that scope. Filesystem
bus/proxy rules remain scoped to that connection; they cannot support a global
service-denial claim through another allowed abstract route. Stronger isolated-IP
or global service filtering is a future capability, not a prerequisite hidden
inside basic networking. No host configuration is changed implicitly.

Children, installers launched at runtime, plugins and embedded browsers inherit
the boundary. Host command execution is not an ordinary environment setting.
Display or audio access carries the scope of the actual protocol: X11 is not a
promise of clipboard or peer-window isolation, and a broad audio socket is not
playback-only. These narrower controls remain unclaimed until enforced.
The same rule applies to shared networking: its service effects cannot be
described as blanket host-command isolation. An explicit denial defeated by a
remaining grant is a policy conflict; no flag ordering can enforce both scopes.
[Flatpak sandbox guidance](https://docs.flatpak.org/en/latest/sandbox-permissions.html).

The portable contract cannot repair incompatible grants by ordering command-line
flags differently. Broad folder/device/service requests that defeat a narrower
denial must produce a conflict or a stated broader effective scope. Linux mode
bits, ACLs, rootless user mappings and SELinux still apply. Device exposure must
not silently disable security policy or relabel unrelated host data. Podman's
privileged mode changes much more than device visibility.
[Podman runtime options](https://docs.podman.io/en/latest/markdown/podman-run.1.html).

Device classes are Q because no engine-independent hotplug implementation has
been selected. Static `--device` mappings are candidates for startup-only access,
not evidence of dynamic node delivery. Qualification records the device universe,
USB versus hidraw paths, supplementary groups, LSM/device controls, enumeration
metadata and event delivery. Podman and Docker require independent mechanisms
and results. Required hotplug needs reconnect/new-node success on all three
claimed adapters; an unsupported result only passes the refusal test. Prefer
existing runtime/broker facilities before designing a mediator.

## MyHarmony application of the design

The [compatibility example](examples/myharmony-compat.cage.yaml) requests broad
native networking, normal X11, optional writable files and All Devices with
required hotplug. Every target uses the same declared device scope; no
format-specific fallback counts as parity. Devices may be absent at startup;
host authorization and real enumeration/sync still need qualification.

The original [strict example](examples/myharmony.cage.yaml) requests selected
USB/hidraw and deliberately has no broader fallback. Flatpak cannot currently
map that direct selector faithfully: it remains a negative export fixture.
Selected-device/portal bridging is a later milestone, not a hidden dependency
of the broad compatibility candidate. Cage never intercepts MyHarmony Sync.

Generated Harmony udev rules authorize the host user, not just one application.
Installing them is separate from accepting sandbox permissions. Rules for one
application must not be removed while another recorded installation needs them;
modified rules must be retained for review. No All Devices request creates a
world-writable udev rule. [Udev rules](https://www.freedesktop.org/software/systemd/man/latest/udev.html).

## Delivery sequence

1. Agree on the contract, normalization and acceptance assertions in this design.
2. Add a shared capability planner and versioned result metadata, reusing the
   existing recipe/graph/export boundaries. Keep the production v0 path intact;
   define state compatibility/adoption before attaching policy to existing plans.
3. Qualify B capabilities on each selected host/runtime tuple, including the
   host-installed AppImage extraction/launch path, fixed baseline and OCI
   deployment contract. Qualify at least one common local x86_64 host/runtime
   matrix across all three formats before claiming practical three-format parity.
4. Add Q capabilities individually; keep F and X outcomes explicit. Integrate
   existing portal/proxy tools before considering a new broker. MyHarmony still
   requires actual online behavior and USB qualification across the three formats;
   the smaller B milestone alone does not satisfy that application goal.
5. Qualify cross-format state transfer only after lifecycle tests pass for each
   independent instance. Never live-share a prefix as a shortcut to parity.

## Design validation

The revised draft 2020-12 JSON Schema and examples are checked structurally with
jsonschema, PyYAML and Cage's strict YAML loader. Validation covers removed fields,
USB presence constraints and explicit hotplug defaults as well as prior negatives.
Schema/example validation is recorded separately from runtime qualification.
Authority, native-edit races, runtime staging and broad-device cases are included.
Removing the proposed fields from the MyHarmony example restores the existing
normalized v0 application recipe. The production parser now supports v1;
implementation replaces that check with correct v1 support and unchanged v0. These
checks do not execute or qualify any proposed runtime capability.

## Decisions to settle before implementation

The structural proposal chooses enforced v1, a uniform request list, one broad
native network grant, launch/integration prerequisites, native portal consent
and a host-installed Cage AppImage launcher. Before implementation, select the
first supported host/tool/runtime tuples and
the exact state compatibility projection/adoption procedure. Qualify the fixed
baseline and native network mappings on those tuples. Before device Q claims,
select and qualify dynamic device mechanisms. Optional permission presentation
can reuse native controls; a new installation UI is not a prerequisite. None
permits an implicit broader fallback
or an unqualified parity claim.

A permission contract digest, export/deployment digest, application/runtime
identity and host capability report must be associated with qualification. This
adds provenance alongside the current verified ownership boundary; it does not
reclassify CFW's prepared state or make an OCI-bound prefix portable.

## Delivery record

Implementation is gated by source/unit verification, native x86_64 adapter
qualification and dedicated physical-device evidence. The local ARM host cannot
qualify native x86_64. HTTP 403 is a blocked application/service check, never
successful login. No user prefix or installed native permissions are adopted
implicitly. Docker, ARM, Wayland, CFW and narrow USB remain separately qualified.
