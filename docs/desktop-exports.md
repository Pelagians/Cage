# Desktop Flatpak exports

Cage's initial desktop target packages a configured Windows x64 application as a local Flatpak. It uses the existing ordered recipe builder under an independently pinned Wine Flatpak runtime. It supports one default entrypoint, offline execution, X11/XWayland, a persistent private Wine prefix, and an explicitly named Documents subdirectory.

The proof application is Notepad++ **8.8.8 portable x64**, identified by its release ZIP SHA-256. This is a deliberately fixed compatibility case, not a claim about arbitrary Windows applications. CFW, Chocolatey, Proton, Linux filesystem layers, additional graphics libraries, suites, MIME associations and automatic upgrades are outside this first target. Their existing Cage workflows remain available through the default container target.

## Build and export

Use an x86_64 Linux machine with Flatpak, Python 3.11 or later, PyYAML, and an X11 desktop or XWayland session. No host Wine, container engine or flatpak-builder installation is required for this target. On a test server, run the commands inside `dbus-run-session` and `xvfb-run` with a window manager.

```bash
python3 scripts/prepare-flatpak-poc.py
python3 -m cage build recipes/notepadplusplus-portable.cage.yaml \
  --target flatpak --output dist/desktop
python3 -m cage export flatpak dist/desktop/notepadplusplus-portable-8.8.8 \
  --dry-run
python3 -m cage export flatpak dist/desktop/notepadplusplus-portable-8.8.8 \
  --output dist/notepadplusplus-8.8.8.flatpak
```

Source preparation downloads only the pinned ZIP, verifies its digest and uses Cage's safe media staging. Existing source staging is never overwritten automatically. The build checks the staged tree against a fresh extraction of the pinned archive, copies the verified inputs, and runs the existing ordered build script against that snapshot.

The builder acquires its Wine base, SDK and platform in `.cage/flatpak`, an isolated Flatpak user installation. `--flatpak-store PATH` selects a different build store. Exact commits are recorded in `runtime/desktop-wine-11.0.json`. The Wine base is the public `org.winehq.Wine` Flatpak; its entire native payload is retained for this proof to avoid guessing which dynamically loaded libraries are unnecessary. It is not the Cage container Wine build or a qualified CFW foundation.

Build-time dependency acquisition needs network access; application installation and launch never install Wine components or invoke Chocolatey. A build downloads shared platform/SDK dependencies, so allow sufficient disk space. The store does not downgrade or modify the user's normal Flatpak installation.

The result includes the `.flatpak`, a JSON export receipt, and a retained `.flatpak.build` directory for inspecting package contents and the local repository. Export refuses to overwrite an existing output or context. A dry run validates the existing desktop bundle and prints its layout, permissions, runtime identity and state policy without downloading runtimes or constructing a package.

## Install and use

On the destination computer, use Flatpak to install the application bundle:

```bash
flatpak install --user dist/notepadplusplus-8.8.8.flatpak
flatpak run io.github.Pelagians.Cage.NotepadPlusPlus
```

The bundle contains runtime repository information for resolving its Freedesktop platform. A `.flatpak` application file alone is not a complete offline distribution of its shared runtime. Flathub provides this normal shared dependency; it does not supply or configure the application-specific Wine prefix.

The application appears as **Notepad++ Cage POC** in the desktop application menu. No separately installed Cage, Wine or Python is required. Python comes from the declared Freedesktop platform. Wine and the complete application seed are inside the application package.

The package grants writable access only to the **Cage** subdirectory of the user's Documents directory, plus Flatpak's private application storage. It has no network permission. Open and save user documents within that directory. Passing an accessible file to the launcher or desktop entry also works; broad filesystem access and portal-based file selection are not part of this proof. X11 permission exposes the host X server and its associated trust boundary; the package does not claim native Wayland isolation.

## Persistence and integrity

The immutable application seed is under `/app/share/cage/<app-id>/seed`. On first launch the helper verifies its complete inventory, locks initialization, copies it into a temporary private prefix, verifies the copy and atomically promotes it. Stale partial copies are retried. If promotion completed before writing the external state receipt, the helper recovers that receipt from the committed marker.

Wine uses `$XDG_DATA_HOME/<app-id>/prefix`. For a normal Flatpak installation this resides under `~/.var/app/<app-id>/data`. Application settings remain inside that writable prefix. Notepad++ deliberately uses its Windows user's `AppData/Roaming/Notepad++` settings when installed under `C:\Program Files`, even from the portable archive; the GUI test checks that active configuration. The seed and exported package stay unchanged. Uninstalling the application should retain its private data unless the user separately requests Flatpak data deletion.

The POC permits one active application launch per prefix. A second launch reports that the application is already running. When the GUI application exits, the helper stops and waits for that prefix's Wine services, then releases its launch lock. This prevents background services from keeping the Flatpak alive and prevents cleanup from terminating another legitimate launch. Multiple simultaneous entrypoints and file handoff to a running application are later integration work.

State records bind the seed digest and runtime identity. An incompatible package generation is refused with its old data retained. Automatic migration, application updates and rollback are later work; replacing a package must not silently launch old binaries or overwrite the user's only prefix.

Both installed files and metadata are covered by Flatpak's content-addressed package commit. The seed additionally has a SHA-256 inventory covering file bytes, types, modes and safe link targets. This inventory detects accidental changes before export and first use; it is not a publisher signature. These local POC bundles are unsigned and are not published by the export command.

## Existing workflows

`cage build` continues to use its existing container target unless `--target flatpak` is specified. A desktop build records its actual execution target alongside the recipe's original OCI runtime intent. Container run and OCI export reject a desktop-built prefix; users must rebuild with the corresponding target. Existing container-built artifacts are not silently rebound to desktop Wine.

No CFW implementation or runtime pin changes are required. CFW desktop support needs a producer-owned desktop contract and its own proofs. Selecting a different Wine version, a custom runner or a CFW prefix cannot bypass that requirement.

Existing container graphs keep `cage.execution-graph/v0`. Desktop graphs use `cage.execution-graph/v1`, with the actual native runtime in the runtime bindings and the original OCI intent retained as `recipeRuntime`. Older verifiers reject this new graph version rather than assuming a desktop prefix belongs to a container image. Updated bundle verification also checks the desktop seed inventory and target receipts.

## Validation

`tests/test_desktop_export.py` covers content tampering, unsafe metadata/paths, runtime mismatch, existing-workflow rejection, source pinning, concurrent initialization, interrupted copying/promotion, persistent settings and generation mismatch. Existing Cage and CFW tests retain their own scope.

The `Desktop Flatpak proof` GitHub workflow runs on x86_64 Ubuntu. It executes the full Cage Python suite, builds and exports the pinned portable application, then installs it in a separate consumer Flatpak store containing the exported app and shared platform rather than a Wine application installation. Under Xvfb/Openbox it launches the installed desktop entry, edits and saves a file whose name includes spaces and Unicode, changes GUI zoom, closes the application, relaunches, appends a second line in the reopened editor and verifies the complete saved file, checks persisted zoom and state identity, and verifies the packaged seed again. JSON receipts, logs, screenshots and the package are retained as workflow artifacts.

This is an automated X11 workflow qualification. Physical GPU behavior, native Wayland, GNOME/KDE file chooser behavior, host clipboard integration, printing, audio and a broader distribution matrix need independent acceptance before they become supported claims. The CI clipboard probe could not read a Wine-owned selection, so the functional check uses an actual second edit/save instead.

## Source and license information

The recipe records the exact portable archive and upstream homepage; the archive includes Notepad++'s license. Notepad++ source for that release is available at `https://github.com/notepad-plus-plus/notepad-plus-plus/tree/v8.8.8`. The pinned Wine Flatpak build source and dependency recipes are recorded by `baseSource` in the runtime lock. Preserve those component notices and satisfy corresponding-source obligations before wider redistribution. Cage's license does not replace licenses of bundled applications or native runtime dependencies. No proprietary CFW or Windows foundation payload is introduced by this POC.
