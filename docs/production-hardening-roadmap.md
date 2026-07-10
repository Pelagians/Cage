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

## Theme 2: Deterministic Chocolatey-for-Wine Integration

### Status

Architecture revised and accepted in [ADR 0022](decisions/0022-deterministic-chocolatey-fork.md). The active experiment uses Noah's narrowly patched fork because the unmodified installer could finalize before its prerequisite workers completed, while Cage's manual CLR reconstruction stalled at managed startup.

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

`core/modules/chocolatey.py` remains a small profile-backed step generator. It does not reimplement Wine, .NET, PowerShell, or Chocolatey installation. The generated container-builder pipeline:

1. loads one immutable compatibility profile;
2. downloads and SHA-256 verifies the fork release plus every transitive installer payload into `CFW_CACHE/choc_install_files`;
3. recreates a private per-prefix work directory and extracts the verified release fresh for each build;
4. runs the patched fork with `CFW_OFFLINE=1`;
5. requires successful installer exit, successful `wineserver` settlement, and canonical `C:/ProgramData/chocolatey/bin/choco.exe`;
6. runs bounded readiness probes, applies feature policy, and proves a local install/uninstall lifecycle;
7. installs requested packages only after those gates pass.

The fork preserves upstream compatibility behavior but serializes finalization after prerequisite workers and propagates child failures. Cage still owns provenance, verified cache preparation, success criteria, diagnostics, and lifecycle evidence.

### Implementation boundaries

| Area | Responsibility |
|---|---|
| `noahgiroux/Chocolatey-for-wine` | Wine compatibility bootstrap, deterministic worker sequencing, offline-cache enforcement, process failure propagation |
| `core/chocolatey/profile.py` | Immutable release and transitive payload URLs/hashes |
| `core/chocolatey/assets/bootstrap.sh` | Verified private staging, fresh release extraction, offline fork execution, and strict bootstrap evidence |
| `core/modules/chocolatey.py` | Package validation and declaration-order build-step generation |
| readiness/policy/lifecycle assets | Independent proof that canonical Chocolatey works before user packages |

### Acceptance criteria

- `modules: - type: chocolatey` loads from strict YAML.
- Every bootstrap payload is pinned, SHA-256 verified, and handed to the fork through its expected cache layout.
- `CFW_OFFLINE=1` prevents network fallback inside the installer.
- Installer, settlement, canonical-file, readiness, policy, and lifecycle failures all fail the build.
- Package names are validated before build-script generation.
- `--module-cache-dir` lets repeated builds reuse verified blobs.
- Runtime containers remain network-isolated by default; Chocolatey is build-time only.

### Parked work

- PowerShell capability `requires`/`provides` resolver and graph/provenance recording — Phase 2.
- Profile/shim layering for Chocolatey + WindowsPowerShell coexistence — not-now until a real recipe needs both Chocolatey packages and WinPS-dependent installers.
- Pre-baked `cage-wine-choco` runtime/build image — proposed after the fork lifecycle passes and bootstrap time becomes the bottleneck.

## Theme 3: End-to-End Production Architecture

Once Themes 1 and 2 are complete, Cage's architecture matches the Gemini-described model:

```
┌─────────────────────────────────────────────────────────┐
│ BUILD PHASE (default networking)                        │
│                                                         │
│  1. Pull base Wine image (or pre-baked choco image)     │
│  2. Initialize Wine prefix                              │
│  3. Run deterministic Chocolatey-for-wine setup         │
│  4. Verify canonical choco.exe                          │
│  5. choco install <packages>                            │
│  6. Install application (exe/msi/portable)              │
│  7. Freeze → OCI image                                  │
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
| 2 | Deterministic Chocolatey MVP path | Medium/large (fork + verified cache + tests) | ADR 0022 | In progress — patched fork is pinned; lifecycle CI is the remaining proof |
| 3 | Network escape hatch (manifest field + CLI flag) | Small (manifest + launcher + kube) | Theme 1 (parallel ok) | Implemented — overridable isolation |
| 4 | External module registry | Medium (module.yaml resolver) | Built-in Chocolatey module proves the pattern | Proposed — cleaner abstraction |
| 5 | Pre-baked chocolatey runtime image | Medium (Dockerfile + CI + GHCR push) | Theme 2 | Proposed — faster builds |

## Review triggers

Create or update an ADR if any theme changes:
- The recipe schema (new `modules[]` field, `runtime.network`)
- The runtime container trust boundary (`--net=none` default)
- The base runtime image set (new chocolatey-baked provider image)
- The build artifact contract (network mode in graph metadata)
