# Native ARM64 Wine/FEX

Cage has an explicit experimental `wine-arm64ec` runtime for Linux ARM64 hosts,
including Fedora Asahi Remix with 16 KB pages. It combines native ARM64 Wine
11.20 with FEX 2610 Windows translation modules. The first qualified application
is the same pinned x64 Notepad++ 8.8.8 portable archive used by the x86_64 proof.
This does not qualify arbitrary Windows applications or CFW prefixes.

Wine implements Windows APIs; FEX translates the application's x86/x64 code.
The Linux Wine loader and shared libraries remain ARM64. No Linux x86 rootfs,
host FEX installation, binfmt registration, KVM or muvm is needed for this case.
Applications with incompatible page-size assumptions may still require a
different execution target; Cage does not silently launch a VM as a fallback.

## Runtime and recipe

`runtime/wine-arm64ec-11.20-fex-2610.json` pins the exact Wine/FEX RPMs by URL and
SHA-256, the extracted payload inventory digest, the packaging source revision,
the native Flatpak platform/SDK commits and the Fedora container base digest.
This Wine build includes the upstream packaging project's ARM64EC/Asahi patches;
an arbitrary Wine 11.20 binary is not an equivalent runtime.

The lock also binds the `fex-2610-cage1` termination guard, its exact replacement
ARM64EC DLL and resulting inventory. The same bytes are used by all ARM export
adapters. Its source, notices, rebuild procedure and state boundaries are documented
in [ARM64EC shutdown guard](arm64-shutdown.md).

`recipes/notepadplusplus-portable-arm64.cage.yaml` is used unchanged for the
container and Flatpak builds. Its application source, file mappings and launch
contract match the existing portable recipe. Its runtime selection is:

```yaml
runtime:
  provider: wine-arm64ec
  version: "11.20"
  network: none
  wineGraphics: xwayland
```

The existing `wine`, `staging` and `umu-proton-ge` defaults and aliases remain
unchanged. Selecting ARM is explicit; Cage does not substitute a different Wine
version for an existing recipe or reuse its prefix under another architecture.

## Flatpak

Build on Linux ARM64 with Flatpak, Python/PyYAML and `rpm2cpio`. On Fedora,
`rpm2cpio` is supplied by `rpm`; on Ubuntu the build package is `rpm2cpio`.
These are producer dependencies, not installed-application requirements.

```bash
python3 scripts/prepare-flatpak-poc.py
python3 -m cage build recipes/notepadplusplus-portable-arm64.cage.yaml \
  --target flatpak --flatpak-store .cage/flatpak-arm64 --output dist/arm-desktop
python3 -m cage export flatpak dist/arm-desktop/notepadplusplus-portable-arm64-8.8.8 \
  --flatpak-store .cage/flatpak-arm64 --timeout 1800 \
  --output dist/notepadplusplus-8.8.8-aarch64.flatpak
flatpak install --user dist/notepadplusplus-8.8.8-aarch64.flatpak
flatpak run io.github.Pelagians.Cage.NotepadPlusPlus
```

Application files and all Wine/FEX components are inside the aarch64 application
package. Flatpak resolves the ARM64 Freedesktop platform as a normal dependency.
The end user does not install or configure Wine, FEX or Cage. The public
`org.winehq.Wine` Flatpak base is not used for this target because it publishes
only x86_64; the x86_64 export target continues to use it.

The producer verifies downloaded RPMs, extracts a bounded selection of runtime
files with a contained cpio reader, then checks the complete extracted inventory
against the pinned digest. Cached payload and inventory changes fail closed.
The existing ordered recipe pipeline runs inside the native Flatpak SDK and
produces a fresh target-compatible prefix. Build stores are independently
selected by `--flatpak-store`.

The package retains the existing permission policy: X11, IPC, an explicitly
named Documents subdirectory and private app storage, with no network or broad
home access. The shared helper verifies and copies the seed once, locks launches,
applies the Windows working directory and preserves the writable prefix under
`~/.var/app/<app-id>/data/<app-id>/prefix`.

The complete unstripped runtime is retained for this first proof. Allow several
GB for the installed package and persistent prefix. Bundle compression can take
several minutes on an M1; the export command above permits 30 minutes per step.

## Containers

Build the native runtime locally, then build the same recipe:

```bash
python3 -m cage container build wine-arm64ec 11.20 --engine podman
python3 -m cage build recipes/notepadplusplus-portable-arm64.cage.yaml \
  --engine podman --output dist/arm-container
```

The ARM catalog entry has no automatic release publication. Its explicit local
build produces `cage/wine-arm64ec:11.20-fex-2610-arm64`. Application builds freeze
the selected carrier to its immutable image identity and record it in the
bundle; later movement of the local tag does not rebind that bundle.

An interactive X11 example, with a dedicated document directory:

```bash
mkdir -p "$HOME/Documents/Cage"
printf 'Hello from ARM\n' > "$HOME/Documents/Cage/example.txt"
python3 -m cage run dist/arm-container/notepadplusplus-portable-arm64-8.8.8 \
  "$HOME/Documents/Cage/example.txt" --engine podman --graphics desktop \
  --state-dir "$HOME/.local/share/cage/notepadplusplus-arm64" --writable-files
```

`--state-dir` explicitly mounts persistent native-container state. Without it,
the container's state is temporary. `--writable-files` grants write access to the
**parent directories** of explicitly passed files, allowing applications to save
by atomic replacement. Passed files remain read-only by default. Planning with
`--dry-run` does not create a state directory.

Desktop mode passes the X11 socket and, when set, the host Xauthority file. For
Podman it disables container SELinux process labeling for this explicit X11
integration; it never relabels the host X socket. X11 access carries the usual
ability to interact with other clients on that display. Network isolation
remains the recipe's default `none`. GPU, audio and device access are not added.

The native image uses the additive `cage.native-wine/v1` lifecycle: root setup
creates a writable private home, then the Wine task runs as the requested
non-root UID/GID. Headless/build modes use a private Xvfb display. Desktop mode
uses the explicitly shared display. This image does not claim the existing
Selkies/Wayland contract. Existing Pelagian Shell containers are unchanged.

Native container launches and Flatpak exports use the same seed inventory,
initialization lock, atomic prefix promotion, generation receipt and application
launch helper. Container state also binds the immutable carrier image. A changed
seed or runtime refuses the old prefix while retaining its data; automatic
cross-runtime migration is not implemented.

Native container bundles can also be assembled by `cage export oci` in headless
or desktop mode. The exported app uses the same helper and persistent state
volume, rather than the legacy launcher. Supply Linux document paths as image
arguments. Desktop image consumers must explicitly share their X11 display.
Kubernetes/hosted ARM deployment is not part of this qualification.

## Qualification and boundaries

Exact local artifact identities, CI links and observed acceptance results are
recorded in the [ARM64 qualification snapshot](arm64-qualification.md).

`scripts/test-arm-container-poc.py` exercises Cage's real container CLI with a
writable document, GUI zoom change, close, relaunch, second edit/save, identical
state generation and unchanged source seed. `scripts/test-flatpak-poc.py` exercises
the corresponding installed desktop-entry workflow, and records the actual
Wine/platform version, installed app reference and kernel page size.

The ARM CI workflow runs the full Python suite and both native GUI proofs on an
ARM64 runner. That runner's page size is recorded; it does not replace validation
on Asahi's real 16 KB kernel. The existing x86_64 Flatpak workflow remains active.

Initial ARM application build modules are `files`, `registry` and `check`.
The desktop proof still accepts only an x64 PE entrypoint; the container runtime
also includes the FEX WoW64 module, with a separate 32-bit command-shell smoke
test. This is not a claim of general 32-bit application compatibility. CFW,
Chocolatey foundations, Proton, custom runners, suites, native Wayland, Selkies,
GPU acceleration, audio, printing and broader distribution/page-size matrices
need their own qualification. Supported kernel page sizes are currently 4 KB
and 16 KB; other sizes fail explicitly.

Wine and FEX remain open source. Preserve packaged notices and corresponding
source obligations, including the recorded patch set, before public distribution.
The proof bundles are local and unsigned; neither export nor CI publishes them.
