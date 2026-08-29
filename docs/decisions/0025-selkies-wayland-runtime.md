# ADR 0025: Selkies Wayland application sessions

- **Status:** Proposed
- **Date:** 2026-08-25
- **Owner:** Cage maintainers / architecture review
- **Reversibility:** Medium; runtime images and run-plan contracts change, while sealed bundle and artifact semantics remain stable

## Context

Cage previously built and launched Wine applications through a framebuffer plus separate browser-proxy helpers. That duplicated session lifecycle, split input and screenshot behavior across unrelated tools, exposed two legacy ports, and made visible execution differ materially from the desktop substrate already proven in Grotto.

Cage must remain an application packager/runtime substrate. Nereus—not Cage—owns workflow admission, policy, scheduling, approval, durable execution lifecycle, and production automation.

## Decision

1. Every catalog image inherits the digest-pinned LinuxServer Selkies Debian Trixie base and retains `/init` and s6. Build, headless, and visible modes are supervised modes of the same image; the retired display stack and sibling image family are removed.
2. Wayland with Labwc is the only desktop-session architecture.
3. `graphics` supports `headless` and `selkies`. Headless uses the same session without publishing a browser endpoint; Selkies publishes HTTPS container port `3001` only.
4. Recipes may set `runtime.wineGraphics` to `xwayland` or `wayland`. Native Wayland is admitted only for Wine Stable and Wine Staging. UMU/GE-Proton is included in the universal Selkies family using XWayland compatibility until its native Wayland path is proven.
5. Wine driver selection uses `HKCU\Software\Wine\Drivers`, value `Graphics`, with `x11` or `wayland`—not an invented environment-only driver contract.
6. PixelFlux is an internal loopback adapter for screenshots and bounded GUI-input fallback. It is not exposed as a Service or public control API.
7. Headless application images retain the catalog runtime entrypoint and use `CMD`; Selkies application images inherit desktop `/init` and set `CAGE_APP_LAUNCHER` instead of replacing `ENTRYPOINT`.
8. Kubernetes Selkies exports require exact live OCI metadata verification, enforce one replica, and add a ClusterIP Service on `3001` behind default-deny ingress. LinuxServer initialization starts as root with only `CHOWN`, `SETGID`, and `SETUID`; privilege escalation and privileged mode remain disabled, all other capabilities are dropped, and services subsequently run as `abc` using `PUID`/`PGID`.

## Preserved contracts

- recipe → build → sealed bundle flow;
- exact catalog runtime binding;
- bundle verification and local artifact index;
- immutable prefix source with separate runtime state and exports;
- OCI application export and digest-pinned Kubernetes export;
- Chocolatey/CFW prepared-runtime ownership boundary; and
- network intent and downstream orchestration boundary.

Cage does not adopt task-worker, compatibility-pack, tenant, approval, or control-plane contracts from other repositories.

## Consequences

- Port `3001` replaces the former multi-port visible-session path.
- All catalog images use the Selkies Debian Trixie parent. Wine package identities use the corresponding Trixie pins; UMU and GE-Proton consume checksum-bound release assets.
- Interactive Kubernetes sessions require an explicit root-init security exception. This needs architecture/security review before deployment.
- A passing XWayland application is not evidence that native Wine Wayland works. Acceptance evidence must report both modes separately.

## Image-role rationale

Routing build scripts through `/init` would break Cage's existing command-exec builder contract and conflate build-time virtual-display needs with an interactive desktop session. Copying Wine filesystem fragments between Debian releases would also violate package ownership and reproducibility. Separate image roles preserve both boundaries.

## Rejected alternatives

- **Keep both desktop architectures:** rejected because it doubles lifecycle and security surface.
- **Override `/init` with a Cage shell entrypoint:** rejected because it bypasses LinuxServer initialization and user/permission handling.
- **Expose PixelFlux externally:** rejected because bounded internal input fallback is not production control authority.
- **Assume every Proton runtime supports native Wayland:** rejected until the exact runner and launch path are behaviorally proven.

## Verification and review trigger

Before implementation is accepted, CI must build every catalog runtime image and the full Python suite must pass. Before deployment, perform a real Notepad++ Chocolatey build and run, screenshot/input/reconnect checks, and bounded shutdown in both XWayland and native Wayland modes. Revisit the security exception if LinuxServer provides a supported non-root initialization path or if the image lifecycle changes.
