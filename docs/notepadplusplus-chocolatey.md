# Notepad++ Chocolatey Recipe

`recipes/notepadplusplus.cage.yaml` is the strict v0, module-first Chocolatey recipe for a Notepad++ proof. It uses the built-in **CFW v1.0.2** prepared runtime with **Wine 11**. CFW owns the compatibility prefix and Wine identity, so this CFW-backed recipe must not declare `runtime.runner` or a Cage `compatibility` block.

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

## Run with noVNC

```bash
python3 -m cage run dist/notepadplusplus-0.1.0 \
  --graphics vnc \
  --network bridge
```

Then open:

```text
http://127.0.0.1:6080
```

If the actual Chocolatey package installs Notepad++ somewhere other than `C:/Program Files/Notepad++/notepad++.exe`, update `launch.entrypoint` after collecting the install result.
