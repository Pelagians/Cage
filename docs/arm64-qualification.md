# ARM64 qualification — 2026-10-20

Implementation revision: `92a4de470e95df121fa0e3f5518952580713cc4b`, branch
`codex/arm64-wine-fex`. Subsequent documentation-only commits do not change the
tested implementation.

This proof runs **Windows x64 Notepad++ 8.8.8** through native ARM64 Wine 11.20
and FEX 2610. It does not substitute a Windows ARM build of the application.
The existing x86_64 runtime and CFW producer bindings remain unchanged.

## Independent execution results

| Environment | Result |
| --- | --- |
| Fedora Asahi Remix 44, `7.1.13-402.asahi.fc44.aarch64+16k`, 16,384-byte pages | Installed Flatpak and Cage container GUI proofs passed |
| Same Asahi host, authenticated isolated X11 display | Cage container save/relaunch proof passed with Xauthority enabled |
| Same Asahi host, normal GNOME/XWayland desktop | Installed user Flatpak's desktop entry opened the saved Unicode-path document |
| Same Asahi host, standalone exported OCI app | Default launch, save, relaunch and persistent state passed; `cage image verify` passed |
| Native ARM64 Ubuntu CI, 4,096-byte pages | Full tests, container GUI proof and clean-store Flatpak install/GUI proof passed |
| x86_64 Ubuntu CI | Full tests and original Wine 11.0 Flatpak GUI proof passed |

[Successful native ARM run](https://github.com/Pelagians/Cage/actions/runs/39390608803).
[Successful x86_64 regression run](https://github.com/Pelagians/Cage/actions/runs/39390608794).
Both ran **455 tests and 173 subtests** successfully. A local Asahi run passed
451 unittest cases; its exclusions were the two wheel-building checks and the
previously identified platform-dependent compressed ZIP byte comparison. The
complete CI suites include those checks.

CFW's unchanged revision `18216a01876c509143b86f857fed3f5f72871257` passed all
**49 Python tests**. This is regression evidence, not CFW-on-ARM qualification.
No real hosted Selkies deployment was requalified by these tests.

## Exact local artifacts

| Item | Identity |
| --- | --- |
| Runtime profile | `wine-arm64ec-11.20-fex-2610-aarch64` |
| Application ZIP SHA-256 | `b8bc370b76653c194caf32450056030be580b9fa97348fb31b2e2e61ee8d2393` |
| Native runtime inventory digest | `e1be53dcd30bf7a9cd6dee073573fdf9a5815fc64ed794455fc38234061503d7` |
| ARM Flatpak | `dist/notepadplusplus-8.8.8-arm64ec-aarch64.flatpak` |
| Flatpak file size | 346,665,408 bytes |
| Flatpak SHA-256 | `cebb0eab51acc50ecc86084fb966a77e5e4b516bf934606552dece672982d85d` |
| Installed app commit | `0e6a654dbc1774bf1886d5d9d8345a8e3253eff13513566c7a84204438ba5fb4` |
| Installed app ref | `app/io.github.Pelagians.Cage.NotepadPlusPlus/aarch64/stable` |
| Observed platform commit | `81382f606af1aa8da7186ef8403a4c429d84968021fa0999fae4f2ffe81aed98` |
| Local container runtime | `localhost/cage/wine-arm64ec@sha256:2b18664b3b240d2f0daf77f046781670ca2f26b7f0458d9374d4b65754489587` |
| Local standalone OCI image ID | `ee4b06c14c263f3de2f026c1daa29faa18ce85a90dd861436f760bd09d494e09` |

The runtime lock records all four exact RPM hashes, the patch/build source
revision, the native platform/SDK commits and the Fedora container base digest.
The local Flatpak SHA-256 was checked against its export receipt after assembly.
Separate CI builds have their own package commits and seed digests because
Wine's fresh prefix initialization creates build-specific state.

## What the GUI assertions established

The Flatpak and Cage container proofs opened a file whose name contains spaces
and Unicode, edited it through the real application, verified the exact saved
host-file contents, changed GUI zoom, closed cleanly, relaunched, appended another
line and verified the complete second save. Zoom and the state-generation receipt
survived both launches. The source seed's complete inventory stayed unchanged.
Container persistence used an explicit `--state-dir`; document writes required
the explicit `--writable-files` grant.

The Flatpak's effective permissions contain X11, IPC and the named Documents
subdirectory, with no network or broad home access. The installed helper uses
the native platform's Python; no host Wine, FEX, binfmt registration or microVM
was used. The actual mounted platform commit was inspected inside the sandbox,
including when Flatpak resolved a system-wide shared runtime.

The standalone OCI image was tested without a Cage CLI in the consumer image,
both with no document argument and with a writable `/exports` document. A
separate headless smoke executed Wine's 32-bit `syswow64/cmd.exe` through FEX.
That does not qualify general 32-bit GUI applications.

## Retained evidence and limits

Local JSON receipts, selected screenshots, image verification and regression
logs are retained in ignored `dist/arm64-qualified/`; raw local GUI evidence is
in `dist/arm64-evidence/`. The successful ARM workflow artifact is
`arm64-wine-fex-92a4de470e95df121fa0e3f5518952580713cc4b`, with a downloaded copy
under `.cage/arm-ci-qualified/`. GitHub retention is 14 days; local copies have
no workflow expiration. The qualified ARM Flatpak is installed for the normal
desktop user and was launched from its installed desktop entry.

This is one application compatibility case. CFW, suites, arbitrary installers,
ARM Selkies/hosted deployment, native Wayland, GPU acceleration, audio, printing,
automatic updates/migrations and other kernel page sizes remain unqualified.
X11 access is an explicit host trust boundary. Unsupported application behavior
on a 16 KB kernel is not automatically redirected through muvm.

See [ARM build/run instructions](arm64-wine-fex.md) for supported commands,
persistence, permissions and source/license information. These artifacts are
local unsigned proofs, not a published release.
