# Cage Production Hardening Roadmap

Status: partially implemented — runtime network isolation implemented; deterministic Chocolatey rebuild accepted and in progress
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

## Theme 2: Upstream Chocolatey-for-wine Integration

### Status

Architecture revised and accepted in [ADR 0019](decisions/0019-upstream-chocolatey-for-wine-wrapper.md). ADR 0018 is preserved as superseded historical context for the failed manual reconstruction path.

### Problem

Chocolatey has a Wine-specific prerequisite chain: CLR/PowerShell setup, Chocolatey bootstrap, profile/QPR compatibility shims, and package install commands must exist inside the prefix before package installation can work. PietJankbal's Chocolatey-for-wine release is not just a file layout; it is the upstream compatibility environment. A partial Cage reimplementation kept rediscovering hidden side effects and produced canonical-looking `choco.exe` layouts that still failed at the CLR boundary.

### Accepted design: `modules[].type: chocolatey`

Recipes still declare package-manager intent as a top-level module:

```yaml
schemaVersion: cage.app/v0
name: my-app
version: "1.0.0"
runtime:
  provider: wine
  version: latest

modules:
  - type: chocolatey
    install:
      packages:
        - firefox
        - 7zip.install
```

The module now lowers that declaration into an upstream-wrapper build path:

1. download the pinned Chocolatey-for-wine release archive.
2. SHA-256 verify and extract it into the module cache.
3. locate `ChoCinstaller_*.exe` and run upstream exactly as documented, with noninteractive/cache flags: `wine ChoCinstaller_*.exe /s /q`.
4. verify canonical `C:/ProgramData/chocolatey/bin/choco.exe`.
5. write Cage diagnostics/metadata before package install.
6. install requested packages only through canonical `C:/ProgramData/chocolatey/bin/choco.exe`.

Synchro's `powershell-wrapper-for-wine` remains a separate capability. `chocolatey` and `powershell-wrapper` stay mutually exclusive until the PowerShell capability resolver lands.

### Phase 1 implementation work

| File / area | Change |
|---|---|
| `core/modules/chocolatey.py` | Wrap pinned upstream Chocolatey-for-wine `ChoCinstaller_*.exe /s /q`, verify canonical Chocolatey, write diagnostics, then install packages |
| `core/manifest/manifest.py` | Keep manifest-level mutual exclusion and reword around capability-provider conflict |
| `core/modules/powershell_wrapper.py` | Add SHA-256 verification to pinned Codeberg downloads |
| CLI / executor | Keep `--module-cache-dir` mounted so Chocolatey-for-wine release/cache payloads survive repeated builds |
| docs/tests/examples | Remove assumptions from ADR 0018's manual PowerShell/nupkg/.NET/native-promotion path |

### Acceptance criteria

- `modules: - type: chocolatey` loads from strict YAML.
- Generated build plan contains named steps for upstream installer, Chocolatey readiness diagnostics, and package install.
- The upstream installer archive is pinned and checksum-verified.
- Generated Chocolatey setup executes `ChoCinstaller_*.exe /s /q` rather than a partial reimplementation.
- Package names are validated before build-script generation.
- Wrapper assets are downloaded from pinned URLs and verified by SHA-256.
- `--module-cache-dir` lets repeated builds reuse downloaded module payloads.
- Runtime containers remain network-isolated by default; Chocolatey is build-time only.

### Parked work

- PowerShell capability `requires`/`provides` resolver and graph/provenance recording — Phase 2.
- Profile/shim layering for Chocolatey + WindowsPowerShell coexistence — not-now until a real recipe needs both Chocolatey packages and WinPS-dependent installers.
- Pre-baked `cage-wine-choco` runtime/build image — proposed after the upstream wrapper works and bootstrap time becomes the bottleneck.

## Theme 3: End-to-End Production Architecture

Once Themes 1 and 2 are complete, Cage's architecture matches the Gemini-described model:

```
┌─────────────────────────────────────────────────────────┐
│ BUILD PHASE (default networking)                        │
│                                                         │
│  1. Pull base Wine image (or pre-baked choco image)     │
│  2. Initialize Wine prefix                              │
│  3. Run upstream Chocolatey-for-wine setup              │
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
| 2 | Upstream Chocolatey wrapper | Medium/large (module steps + cache + tests) | ADR 0019 | In progress — recipe authors still declare `modules: - type: chocolatey`; Cage wraps upstream `ChoCinstaller_*.exe /s /q` with diagnostics |
| 3 | Network escape hatch (manifest field + CLI flag) | Small (manifest + launcher + kube) | Theme 1 (parallel ok) | Implemented — overridable isolation |
| 4 | External module registry | Medium (module.yaml resolver) | Built-in Chocolatey module proves the pattern | Proposed — cleaner abstraction |
| 5 | Pre-baked chocolatey runtime image | Medium (Dockerfile + CI + GHCR push) | Theme 2 | Proposed — faster builds |

## Review triggers

Create or update an ADR if any theme changes:
- The recipe schema (new `modules[]` field, `runtime.network`)
- The runtime container trust boundary (`--net=none` default)
- The base runtime image set (new chocolatey-baked provider image)
- The build artifact contract (network mode in graph metadata)
