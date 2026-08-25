# Cage Container Architecture

## Two image roles

Cage deliberately separates build/headless runtimes from interactive desktop runtimes.

### Build and headless runtime images

`container/runtimes/*` remains the deterministic prefix-construction substrate selected by `runtime/catalog.json`. These Debian Bookworm images retain a build-only Xvfb display because Windows installers can require an X server even during non-interactive builds. The obsolete VNC/browser-proxy packages are removed.

These images preserve the command-exec entrypoint used by `builder/executor.py` and by `cage run --graphics headless`.

### Selkies desktop images

`container/desktop/*` is a sibling image family for interactive application execution. Each image:

- inherits the digest-pinned LinuxServer Selkies Debian Trixie base;
- installs the corresponding Wine or Wine Staging runtime independently;
- preserves inherited `ENTRYPOINT ["/init"]` and s6;
- uses Wayland and restricted Labwc;
- publishes Selkies HTTPS on container port `3001`; and
- keeps PixelFlux screenshot/input support on container loopback.

The desktop images do not copy package-manager-owned Wine files out of the build images. Their Debian release, lifecycle, and user model are independent and are tested as such.

```text
recipe/build
  -> catalog build image (Bookworm + build-only Xvfb)
  -> sealed Cage bundle
  -> headless run using catalog image
     OR
  -> interactive run/export using sibling Selkies desktop image
```

## Runtime metadata

The execution graph keeps `builderRuntime` and `runnerRuntime` for Cage's existing exact-runtime contract. `runnerRuntime.desktopImage` and `localDesktopImage` identify the separate interactive target. A CFW producer-owned prepared runtime must explicitly provide both:

```text
sessionContract: cage.selkies-wayland/v1
selkiesImage: ghcr.io/pelagians/cage-wine-selkies@sha256:<digest>
```

Absent that pair, headless build/run remains valid but Selkies launch and Selkies OCI export fail closed.

## Desktop lifecycle

LinuxServer `/init` starts as root, applies `PUID`/`PGID`, runs `custom-cont-init.d`, and launches services and the application as `abc`. Cage never replaces `/init`.

`container/selkies/root/defaults/autostart_wayland` launches either:

1. a base64-encoded local `cage run` script; or
2. `CAGE_APP_LAUNCHER` in an exported Selkies application image.

Wine graphics selection uses `HKCU\Software\Wine\Drivers`, value `Graphics`:

- `xwayland` selects `x11`;
- `wayland` selects Wine's native Wayland driver.

Native Wayland is admitted for Wine Stable and Wine Staging. No UMU/GE-Proton desktop image is published until its upstream artifacts and launch path are independently pinned and proven.

## CLI modes

```bash
cage run --graphics headless dist/app-1.0.0
cage run --graphics selkies --network bridge --selkies-port 3001 dist/app-1.0.0

cage export oci dist/app-1.0.0 --graphics headless --tag cage-app:headless
cage export oci dist/app-1.0.0 --graphics selkies --tag cage-app:desktop
```

Headless OCI images retain the base runtime entrypoint and set the Cage launcher as `CMD`. Selkies OCI images inherit `/init` and set `CAGE_APP_LAUNCHER` for the supervised Wayland session.

## Kubernetes

A headless export emits the existing Deployment/PVC/network-policy resources. A Selkies export requires a successful `cage image verify` receipt for the exact digest-pinned application image, enforces one replica, and emits a ClusterIP Service on HTTPS port `3001` plus default-deny ingress. Nereus or an operator must add an explicit authenticated ingress policy before any client can reach the session.

Interactive LinuxServer initialization requires root PID 1 with only `CHOWN`, `SETGID`, and `SETUID`; privilege escalation and privileged mode remain disabled, all other capabilities are dropped, and `RuntimeDefault` seccomp remains enabled. Nereus or the operator owns admission, ingress, authentication, policy, and lifecycle.

## SELinux mounts

Rootless Podman bind mounts retain the shared `z` label for the read-only bundle, optional files, and runner cache. Persistent `/config` belongs to the desktop session and must remain separate from the sealed bundle and Cage runtime state.
