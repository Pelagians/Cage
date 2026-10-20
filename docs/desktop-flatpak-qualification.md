# Flatpak proof qualification — 2026-10-20 UTC

Phases 1 and 2 passed their first application workflow proof at source revision
`413f6977100c09c8974a0e67045fbf2f4ea8f8f5` on branch
`codex/flatpak-desktop-poc`.
[Successful CI run](https://github.com/Pelagians/Cage/actions/runs/39382878395).
Subsequent documentation-only changes do not change this tested source snapshot.

## Qualified case

| Component | Identity |
| --- | --- |
| Application | Notepad++ 8.8.8 portable x64 |
| Source ZIP SHA-256 | `b8bc370b76653c194caf32450056030be580b9fa97348fb31b2e2e61ee8d2393` |
| Wine | `wine-11.0`, public `org.winehq.Wine` stable Flatpak base |
| Wine base commit | `2b7feee9cd37329c1fecd0c45960b0634cd0e684a3f1fd895df8771612ed2865` |
| Shared platform | `org.freedesktop.Platform/x86_64/26.08` |
| Installed platform commit | `92659297ffdb4f9f14dd1562bd919b48160b0dc42c99653dcfc0688096af41df` |
| Installed app commit | `31c9618efe6f6b43ca9ae107123b409b6363fdf42fcdcc3b27fe7d77743a518e` |
| Exported file SHA-256 | `f8bff55e6f38eeceaaf1e77c0aba31fb0a389d86bcb540292847d6ffcdfcc048` |
| Exported file size | 85,937,776 bytes |
| Seed inventory digest | `37aeeb4cf3e13290edb66b8a0e4abc6f90035a61e3248c54d3b0fbb0661e28c3` |
| Normalized manifest digest | `501fa6a835446d7123b032d7f60a5e65669b05713e51d3e3ccc23c347a9079be` |
| Test desktop | Ubuntu 24.04 x86_64 CI, Xvfb/Openbox, Flatpak 1.14.6 |

The build runtime lock also pins the SDK commit and links the Wine base's build
source, including dependency recipes. The package retains the base payload and
application notices; it records application sources and runtime source references
under `/app/share/cage/<app-id>/component-sources.json`. This is a local unsigned
POC, not a public release or a completed corresponding-source distribution.

## Observed acceptance results

- Full Cage suite: **447 tests and 173 subtests passed** on x86_64.
- CFW: **49 Python tests passed**, at unchanged revision
  `18216a01876c509143b86f857fed3f5f72871257`. This is regression testing,
  not desktop qualification of a CFW foundation.
- A separate, initially empty consumer Flatpak store installed the `.flatpak`
  directly. Flatpak resolved the platform and its normal graphics/codec
  extensions automatically. No Wine application or SDK was installed in that
  store; neither host Wine nor the Cage CLI was available. No container engine
  was invoked by the desktop build, export or application.
- The installed desktop entry launched the real application with
  `Documents/Cage/Desktop proof café.txt`, covering spaces and a Unicode path.
- GUI input replaced the document and saved the exact expected contents. The
  test selected View → Zoom → Zoom In, closed the application and waited for
  the prefix's Wine services to stop.
- The same desktop entry relaunched the saved document. GUI input appended
  `Relaunch verified` and saved again; the complete file contained both the
  original edited text and the appended line.
- Zoom persisted as `1` through both closes in the active Windows user's
  `AppData/Roaming/Notepad++/config.xml`. The state receipt stayed identical;
  the prefix was not reinitialized.
- The installed package commit stayed identical, and the helper verified the
  complete immutable seed inventory after both launches.
- Recorded permissions grant X11, IPC and `xdg-documents/Cage:create`; no network
  or broad home/host filesystem permission is present.

Unit tests separately exercise tampered payloads, unsafe links/special files,
runtime mismatches, source archive binding, interrupted initialization and
receipt recovery, concurrent first use, a rejected second active launch and
rejection by container/OCI/Kubernetes paths. They do not substitute for the real
GUI proof above.

## Retained evidence and limits

The successful workflow artifact is
`desktop-flatpak-poc-413f6977100c09c8974a0e67045fbf2f4ea8f8f5`.
A downloaded copy is retained locally in ignored `dist/qualified-flatpak/`:
the package, export receipt, build metadata, logs, screenshots and
`desktop-evidence/functional-test.json`. Its package SHA-256 was checked against
the export receipt after download. GitHub's artifact retention is 14 days; the
local copy has no such workflow expiration.

This qualifies one offline, single-entrypoint application under automated X11.
The ARM64 development host did not run this x86_64 package. Cross-user identity
changes, physical GPUs, native Wayland, GNOME/KDE file choosers, host clipboard,
printing, audio and other distributions/applications need separate qualification.
The initial host clipboard probe could not read a Wine-owned selection; the
accepted proof uses a second real edit/save instead.

AppImage assembly, automatic updates/migrations, portal integration, multiple
entrypoints and CFW desktop support remain later phases. Incompatible seed/runtime
generations currently refuse to launch while retaining existing user data.
Existing container/hosted workflows retain their defaults and runtime gates;
their full real deployments were not requalified by this desktop GUI run.

See [desktop export usage](desktop-exports.md) for build/install commands and
the current runtime, state and permissions contract.
