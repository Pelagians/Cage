# Notepad++ Chocolatey Recipe

`recipes/notepadplusplus.cage.yaml` is the strict v0, module-first Chocolatey recipe for a Notepad++ proof. It uses the built-in **CFW v1.0.3** prepared runtime with **Wine 11**. CFW owns the compatibility prefix and Wine identity, so this CFW-backed recipe must not declare `runtime.runner` or a Cage `compatibility` block.

## Inspect

```bash
python3 -m cage inspect recipes/notepadplusplus.cage.yaml
```

## Build

The current CLI exposes build as top-level `build` rather than `bundle build`.

```bash
python3 -m cage build recipes/notepadplusplus.cage.yaml \
  --output dist \
  --module-cache-dir .cage-module-cache
```

## Verify

```bash
python3 -m cage bundle verify dist/notepadplusplus-0.1.0
```

## Run with Selkies

```bash
python3 -m cage run dist/notepadplusplus-0.1.0 \
  --graphics selkies \
  --network bridge
```

Then open:

```text
https://127.0.0.1:3001
```

If the actual Chocolatey package installs Notepad++ somewhere other than `C:/Program Files/Notepad++/notepad++.exe`, update `launch.entrypoint` after collecting the install result.


## Selkies migration acceptance status

The recipe and Chocolatey module remain the canonical Notepad++ acceptance path. The currently pinned producer-owned CFW runtime does **not** declare `sessionContract: cage.selkies-wayland/v1`, so Cage fails closed before launch or OCI application export rather than pretending that image inherits `/init`.

Required evidence after CFW publishes and Cage pins a qualified runtime:

| Check | XWayland | Native Wine Wayland |
| --- | --- | --- |
| CFW prepared-prefix import and package receipt verification | NOT RUN | NOT RUN |
| Notepad++ process and visible window | NOT RUN | NOT RUN |
| PixelFlux PNG screenshot | NOT RUN | NOT RUN |
| Bounded click/type fallback | NOT RUN | NOT RUN |
| Selkies HTTPS reconnect | NOT RUN | NOT RUN |
| Clean bounded shutdown | NOT RUN | NOT RUN |

XWayland success must not be reported as native-Wayland success. The producer image release, updated immutable digest, and live matrix are merge gates for declaring the migration complete.
