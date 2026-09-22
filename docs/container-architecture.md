# Cage Container Architecture

## One universal runtime image per catalog entry

Every image selected by `runtime/catalog.json` inherits one immutable Pelagian Shell digest. There is no parallel build/headless or desktop image family.

The nine catalog entries cover Wine Stable, Wine Staging, and UMU + GE-Proton. Each image:

- preserves Pelagian Shell's inherited `/init` and s6 lifecycle;
- starts the Wayland/Labwc session as `abc` after bounded root initialization;
- includes Selkies HTTPS on container port `3001`;
- includes internal PixelFlux support;
- supports build, headless application, and visible interactive modes through environment-delivered supervised scripts;
- contains no retired virtual-display or browser-proxy session contract.

```text
recipe
  -> one catalog runtime image
  -> build script through /init + Labwc
  -> sealed bundle
  -> headless or visible run through the same image and /init
  -> optional OCI application image inheriting the same /init
```

## Pelagian Shell consumer boundary

The catalog images use the accepted dependency:

```text
LinuxServer Selkies -> Pelagian Shell -> Cage catalog runtime
```

Each Dockerfile pins `ghcr.io/pelagians/pelagian-shell@sha256:...` directly. Cage no longer copies a generic Labwc baseline or replaces Shell autostart. It installs only `/usr/local/bin/pelagian-shell-consumer` for Cage application launch; Pelagian Shell owns session initialization, Labwc policy, theme, and streaming defaults.

Cage must retain its own Wine/Proton packages, Wine graphics selector, `CAGE_*` launch contract, s6 build/task/shutdown services, `/var/lib/cage` state and receipts, `/exports`, bundle handling, and application-specific runtime policy. Pelagian Shell does not install Wine, execute Cage tasks, or own Cage's artifact lifecycle.

The existing nine-image and live Wine/XWayland/Wayland qualification gates still apply to every published Cage runtime.

## Graphics modes

`runtime.wineGraphics: xwayland` selects Wine's X11 driver under Selkies' XWayland compatibility service. `wayland` selects Wine's native Wayland driver and is limited to Wine Stable and Wine Staging. UMU + GE-Proton uses XWayland until its native Wayland path is independently proven.

Both `cage run --graphics headless` and `--graphics selkies` preserve `/init`. Headless mode does not publish a host port; visible mode requires bridge networking and binds `127.0.0.1:<port>:3001`.

## Producer-owned CFW runtimes

A CFW runtime is also one image. A producer release must bind its digest-pinned `wineImage` to:

```yaml
sessionContract: cage.selkies-wayland/v1
```

The removed `selkiesImage` sibling field is rejected. Existing immutable pre-Selkies CFW artifacts fail closed until CFW republishes them from the universal image.

## Kubernetes

All generated application images inherit `/init`, so all exported Deployments retain the narrow Pelagian Shell initialization security context and `/config` volume. Visible Selkies export additionally requires exact live OCI verification, one replica, a ClusterIP service on `3001`, and default-deny ingress. Nereus owns admission and any authenticated ingress policy.

## Live acceptance gates

The runtime catalog has nine image entries. CI builds the affected entries on
source changes and the full matrix on a manual catalog qualification. Runtime
acceptance must prove `/init`, s6, `abc` ownership, build completion receipts,
headless completion, Selkies HTTPS, XWayland for all providers, native Wayland
for Wine/Staging, PixelFlux, reconnect, and a separately qualified CFW/Notepad++
flow. Release tags move only after the candidate digest passes its runtime gates.

### Live Shell qualification

The consumer pins the Shell image published from
`Pelagians/pelagian-shell@fe25c6756d7976322be97ece671ca8f9f9e5c7f7`
(Shell PR #7). CI checks out the shared conformance harness at
`a9c6100aabc0cb79deb43910e92639f9b92b4a3d` and verifies the viewer's
SHA-256 before execution. CI starts the inherited `/init`, decodes
1920x1080 streamed frames, and checks the real application window through Labwc
IPC: healthy reconciliation, maximized usable-area geometry, visible titlebar,
and no fullscreen state. Multiwindow reflow and dialog policy remain owned and
qualified by the Shell repository.

Wine and Wine Staging matrix entries launch Notepad using the XWayland driver;
Wine 11.0 also runs under rootless Podman. Use
`CONTAINER_ENGINE=docker tests/smoke-shell-runtime.sh IMAGE` to repeat the check.
The legacy-apps Shell profile enables Wine defaults, imported only after Cage
selects its writable runtime prefix. The source bundle remains untouched.

UMU/Proton entries retain the real-session environment import gate. This does
not qualify a UMU game launch or native Wine Wayland. The immutable Chocolatey
runtime artifacts retain their separately qualified digest and must be rebuilt
and qualified before their trust records can be advanced.
