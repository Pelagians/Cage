# Cage Container Architecture

## One universal runtime image per catalog entry

Every image selected by `runtime/catalog.json` inherits the digest-pinned LinuxServer Selkies Debian Trixie base. There is no parallel build/headless or desktop image family.

The nine catalog entries cover Wine Stable, Wine Staging, and UMU + GE-Proton. Each image:

- preserves LinuxServer `/init` and the s6 lifecycle;
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

The current catalog images still derive directly from LinuxServer Selkies and copy `container/selkies/root/`. The accepted follow-up dependency is:

```text
LinuxServer Selkies -> Pelagian Shell -> Cage catalog runtime
```

After Cage qualifies an immutable `ghcr.io/pelagians/pelagian-shell@sha256:...` input, that migration should remove the duplicated generic substrate: the direct Selkies `FROM`, generic Labwc baseline/theme, generic session initialization, and generic port-3001 streaming defaults.

Cage must retain its own Wine/Proton packages, Wine graphics selector, `CAGE_*` launch contract, s6 build/task/shutdown services, `/var/lib/cage` state and receipts, `/exports`, bundle handling, and application-specific runtime policy. Pelagian Shell does not install Wine, execute Cage tasks, or own Cage's artifact lifecycle.

This document records the boundary only. The runtime switch remains blocked on a digest-pinned Pelagian Shell release plus Cage's existing nine-image and live Wine/XWayland/Wayland qualification gates.

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

All generated application images inherit `/init`, so all exported Deployments retain the narrow LinuxServer initialization security context and `/config` volume. Visible Selkies export additionally requires exact live OCI verification, one replica, a ClusterIP service on `3001`, and default-deny ingress. Nereus owns admission and any authenticated ingress policy.

## Live acceptance gates

CI must build all nine image entries. Runtime acceptance must prove `/init`, s6, `abc` ownership, build completion receipts, headless completion, Selkies HTTPS, XWayland for all providers, native Wayland for Wine/ Staging, PixelFlux, reconnect, and a republished CFW/Notepad++ flow.
