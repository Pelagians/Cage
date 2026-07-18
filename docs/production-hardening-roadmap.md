# Cage Production Hardening Roadmap

Status: partially implemented — runtime network isolation implemented; deterministic fork lifecycle validation in progress
Date: 2026-07-02

## Objective

Move Cage from "working tool" toward "production-ready platform" by hardening the networking model, introducing a module system for build-time tooling, and proving the architecture with Chocolatey as the first module.

These changes are independent of the [legacy-installer-debugging-backlog](legacy-installer-debugging-backlog.md) — they address the runtime security and build-automation layers, not individual installer debugging workflows.

---

## Theme 1: Runtime Network Isolation

### Problem

Without explicit runtime network isolation, a deployed Win32 application inside Wine can reach the internet, scan the LAN, or beacon out — undermining the air-gapped security model that makes legacy-Wine-in-containers attractive.

### Design

| Phase | Network default | Rationale |
|---|---|---|
| **Build** | Default bridge (unchanged) | Needs internet to git clone wrappers, run `choco install`, download winetricks verbs |
| **Runtime** | `--net=none` (new default) | Win32 app inside Wine should have zero network access |

### Escape hatch

Some runtime scenarios need local connectivity (host database, local printer service), or interactive VNC/noVNC access. Two mechanisms:

1. **CLI flag** — `cage run my-app --network host|bridge|none`
2. **Manifest field** — `runtime.network` recorded in bundle graph metadata so intent survives packaging

The manifest field captures *intent*; the CLI flag allows the operator to *override* at deployment time for extra hardening. Bundle verification requires `manifest.runtime.network` to match `metadata/graph.json` `runnerRuntime.network` so graph tampering cannot silently escalate a default air-gapped bundle to host networking. Local VNC/noVNC runs are intentionally limited to `--network bridge` so Docker/Podman host-port publishing can bind access to loopback; the VNC helpers still listen inside the container, so bridge-mode VNC should not be attached to an untrusted/shared container network. `none` is non-interactive air-gap mode and `host` is rejected for VNC.

### Implemented changes

| File | Change |
|---|---|
| `core/manifest.py` | Add `network` field to `RuntimeSpec` (default: `"none"`) |
| `runtime/launcher.py` | `_container_argv()` emits `--net none` by default, reads overrides |
| `artifact/graph.py` | Carries `network` into `metadata/graph.json` under `runnerRuntime.network` |
| `artifact/kube.py` | Set `hostNetwork` or emit `NetworkPolicy` based on graph metadata |
| `cage/cli.py` | `cage run --network <mode>` flag |

### Implemented acceptance criteria

- `cage run my-app` starts container with `--net none` by default
- `cage run my-app --network host` uses host networking for headless runs
- `cage run my-app --graphics vnc --network bridge` keeps host-published VNC/noVNC access loopback-bound
- VNC with `network: none` or `network: host` is rejected instead of producing a broken or exposed plan
- Bundle graph records `network: "none"` for default builds
- `cage export kube` emits appropriate network config, with deny-egress policy for `network: none` when the cluster CNI enforces NetworkPolicy
- Existing build containers are unaffected (keep default networking)

---

## Theme 2: CFW Prepared-Runtime Consumption

### Status

Architecture revised in [ADR 0024](decisions/0024-cfw-prepared-runtime-provider.md). CFW owns Windows/Wine compatibility construction and must publish a passing immutable prepared-prefix release before Cage enables its consumer lifecycle.

### Accepted design: `modules[].type: chocolatey`

Recipes declare only package-manager intent:

```yaml
modules:
  - type: chocolatey
    install:
      packages:
        - firefox
        - 7zip.install
```

`core/modules/chocolatey.py` remains a small consumer step generator. The generated pipeline:

1. validates the runtime profile and package names during manifest parsing;
2. selects the exact digest-pinned CFW producer image and producer-declared environment before container execution;
3. verifies the detached manifest before trusting archive or evidence digests;
4. requires complete source, installer, input-lock, Wine-image, producer-declared environment/interface, and behavioral-proof bindings; CFW profile-loader internals remain opaque to Cage;
5. safely extracts into a temporary directory and replacement-seeds only after archive-member validation;
6. performs a bounded Wine update, readiness checks, and verification-only feature-policy checks;
7. proves a local package install/uninstall lifecycle before requested packages;
8. exports the resulting application artifact.

Cage does not reconstruct CLR, GAC, PowerShell, Synchro, Chocolatey bootstrap, profiles, registry policy, or DLL compatibility. A separate downloaded `runtime.runner` is forbidden for a CFW artifact because it would invalidate the producer image’s Wine identity.

### Implementation boundaries

| Area | Responsibility |
|---|---|
| `noahgiroux/Chocolatey-for-wine` | Compatibility construction, exact inputs, runtime proofs, prepared-prefix archive, evidence, and detached manifest |
| `core/modules/chocolatey.py` | Strict recipe/profile validation and declaration-order consumer steps |
| `core/chocolatey/assets/runtime-artifact.py` | Manifest/evidence verification and safe temporary extraction/promotion |
| readiness/policy/lifecycle assets | Verification of imported behavior and requested package execution, without compatibility reconstruction |

### Acceptance criteria

- A real CFW Wine 11 producer run passes every required behavioral proof.
- CFW publishes immutable archive, evidence, manifest, and checksum assets.
- Cage pins the detached manifest digest and exact producer image.
- Unsafe profile values and unsafe archive members are rejected before prefix replacement.
- Missing producer assets fail the workflow rather than yielding a green skipped lifecycle.
- Cage’s package lifecycle and requested package install pass against the exact released runtime.

### Parked work

- Installer/component consumption instead of prepared-prefix replacement — revisit only if bounded prefix updates cannot preserve the released runtime.
- Wine 9/10 expansion — after Wine 11 producer and consumer paths pass.
- Additional PowerShell capability composition — only for a concrete application requirement not provided by CFW.

## Theme 3: End-to-End Production Architecture

Once Themes 1 and 2 are complete, Cage's architecture matches the Gemini-described model:

```
┌─────────────────────────────────────────────────────────┐
│ BUILD PHASE (default networking)                        │
│                                                         │
│  1. Pull the exact digest-pinned CFW producer image     │
│  2. Verify manifest, evidence, archive, and interfaces  │
│  3. Replacement-seed the verified prepared prefix      │
│  4. Run bounded prefix update and readiness checks      │
│  5. Prove local package install/uninstall lifecycle     │
│  6. choco install <requested packages>                  │
│  7. Install application and freeze → OCI image          │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ RUNTIME PHASE (--net=none, air-gapped)                  │
│                                                         │
│  Ingress Pod → shared volume → Cage App Container   │
│                                   (processes data       │
│                                    via Win32/Wine)      │
│  shared volume → Egress Pod                             │
│                                                         │
│  Application has zero network access.                   │
│  All data flow is through volume mounts.                │
└─────────────────────────────────────────────────────────┘
```

---

## Sequencing

| Order | Theme | Effort | Dependencies | Delivers |
|---|---|---|---|---|
| 1 | Runtime `--net none` default | Small (1–2 files + tests) | None | Implemented — immediate security hardening |
| 2 | Deterministic Chocolatey MVP path | Medium/large (CFW producer + verified consumer + tests) | ADR 0024 | In progress — static producer/consumer boundaries exist; immutable Wine 11 release and non-skipped lifecycle remain |
| 3 | Network escape hatch (manifest field + CLI flag) | Small (manifest + launcher + kube) | Theme 1 (parallel ok) | Implemented — overridable isolation |
| 4 | External module registry | Medium (module.yaml resolver) | Built-in Chocolatey module proves the pattern | Proposed — cleaner abstraction |
| 5 | Additional prepared-runtime producers | Medium (producer contract + CI + immutable release) | Theme 2 | Parked — only after Wine 11 CFW proof |

## Review triggers

Create or update an ADR if any theme changes:
- The recipe schema (new `modules[]` field, `runtime.network`)
- The runtime container trust boundary (`--net=none` default)
- The base runtime image set (new chocolatey-baked provider image)
- The build artifact contract (network mode in graph metadata)
