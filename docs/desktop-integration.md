# Desktop integration, file access and scaling

Both desktop exporters consume the existing recipe `entrypoints` and
`fileAssociations` metadata. This qualification supports one entrypoint identical
to the default `launch` (executable, arguments, environment and working directory).
Other suite entrypoints remain unsupported for desktop export. The portable
Notepad++ recipes offer `text/plain` through their desktop files. Existing MIME
registrations determine filename extensions; Cage does not install conflicting
extension definitions or change the user's default editor.

Flatpak exports its desktop file using normal Flatpak file forwarding. An
explicitly selected file outside `Documents/Cage` is passed through the document
portal. Its Wine filename refers to that sandbox-visible path. This requires a
working host document portal; it does not grant access to the file's siblings or
parent directory. A Windows file chooser is not a native portal chooser. For new
files and Save As, select the declared writable `Documents/Cage` directory or
private application storage. Unselected host directories remain unavailable.

AppImage offers the same MIME handler after explicit `--cage-install`. It uses
ordinary host-user access and refreshes the desktop MIME cache when the host
provides `update-desktop-database`. Installation does not change `mimeapps.list`.
The stable installed dispatcher continues to select the retained package matching
the active generation. Uninstall removes only recorded installation files and
retains application state and documents.

Both launchers accept readable files, local `file:` URIs and new filenames in
existing accessible writable directories. Directories, remote URLs and paths
Wine cannot represent fail with an error. Files passed after `--` cannot be
interpreted as Cage lifecycle options.

## Display scaling

New exports share the same font families from the pinned Freedesktop platform
and the same fontconfig aliases. AppImage previously carried only DejaVu fonts;
its font selection could differ from Flatpak. There is no host font dependency
or font download at launch.

Missing Windows font families also receive Wine GDI replacements (for example,
Courier New to Liberation Mono). Fontconfig aliases alone do not provide those
Windows family names. Existing user replacements and application font settings
are retained; Wine uses an installed real family ahead of a replacement. See
[Wine's replacement implementation](https://github.com/wine-mirror/wine/blob/wine-11.0/dlls/win32u/font.c).

The launcher reads the X11/XWayland session's logical `Xft.dpi` and sets Wine's
`HKCU\Control Panel\Desktop\LogPixels` before starting the application. It uses
96 DPI when no value is available, with a supported range of 96–384. This scales
the application's menus and dialogs as well as text; resizing a window or using
Notepad++ editor zoom does not set UI scaling.

```sh
flatpak run --user io.github.Pelagians.Cage.NotepadPlusPlus --cage-display-info
flatpak run --user io.github.Pelagians.Cage.NotepadPlusPlus --cage-dpi 192
./application.AppImage --cage-dpi 192

# Return to automatic session scaling, or disable Cage's DPI changes.
./application.AppImage --cage-dpi auto
./application.AppImage --cage-dpi preserve
```

Close the application before changing the preference, then relaunch it. The
preference lives in `display.json` beside `state.json`, separately for each
format, and survives application updates and rollback. Existing custom Wine DPI
is retained when automatic mode first encounters it; subsequent manual Wine DPI
changes are also respected. To explicitly replace a custom value, set a numeric
DPI. Seed payloads and retained generations are never rewritten as a group.
An older package retains its original launcher behavior when rolled back.

This is session-level X11/XWayland scaling, not dynamic per-monitor DPI support.
Mixed-scale monitors, moving a running window between monitors and native Wine
Wayland need separate qualification. GNOME fractional scaling can advertise an
XWayland DPI different from its logical monitor scale; Cage follows `Xft.dpi`
without applying another toolkit scale multiplier.

## Qualification

The update CI matrix runs on native x86_64 and aarch64. It uses a private test
state, real exported packages and a real X11 desktop. The extended proof checks
MIME metadata, desktop launches, Flatpak file forwarding of a read-only Unicode
filename outside the permanent grant, Save As to a new host file, new-file
creation, selected writable-file save and relaunch, 192-DPI selection and
settings/documents through update and rollback.
Flatpak's test desktop file retains the exported forwarding arguments but uses a
wrapper to set private state inside the sandbox; normal user data is untouched.
Screenshots and result JSON are retained with update qualification evidence.

Qualification completed for the pinned portable Notepad++ 8.8.8 → 8.8.9 → 8.8.8
profile at source revision `dce3885bf839157573e9a0b8430ecdacac0031a1`:

| Environment | Flatpak | AppImage | Container / OCI regression |
| --- | --- | --- | --- |
| Native x86_64 CI, 4 KiB pages | Passed | Passed | Existing contract suite |
| Native ARM64 CI, 4 KiB pages | Passed | Passed | Passed |
| Asahi Linux, Apple M1, 16 KiB pages | Passed | Passed, including FUSE execution | Separate existing qualification |

[The complete CI run](https://github.com/Pelagians/Cage/actions/runs/39516599623)
retains result JSON, logs and screenshots. Each desktop proof uses eight real GUI
sessions: baseline, update, relaunch, rollback, relaunch, new-file creation and
two selected writable-file sessions. It verifies executable hashes, saved file
contents, retained editor zoom, latest prefix documents and all three generation
records. The Flatpak proof also checks that an unselected sibling outside the
permanent grant remains inaccessible. Build-staging cleanup retains verified
packages and provenance before the consumer tests run.

The local suite passed 520 tests and 192 subtests, covering existing export,
container, CFW-consumer, update and storage contracts. The Asahi proofs used a
private X11 desktop at 192 DPI and private application state; the user's normal
installations, settings, documents and rollback data were not replaced. Both
exports contained the same 88 font files, byte-identical fontconfig and the same
desktop launcher. Find-dialog screenshots were visually checked for matching
font and control metrics; Courier New fallback was checked for monospace text.
Wine still supplies its classic controls, rather than the host's GTK theme.

Local evidence is retained in
`.cage/desktop-integration-local-verification.json`,
`.cage/desktop-integration-ci-verification.json` and
`dist/appimage-evidence/asahi-desktop-{flatpak-final-v5,appimage-final}/`.
Qualified ARM64 packages are retained under
`dist/desktop-integration-packages/{8.8.8,8.8.9}.flatpak` and
`dist/desktop-integration-final/{8.8.8,8.8.9}.AppImage`, with export and relocation
receipts. These are local unsigned proof packages, not published releases.

Qualification is specific to this application profile and these environments.
It does not establish compatibility for arbitrary Windows applications, native
Wine Wayland or dynamic mixed-monitor scaling. The existing exclusive session
lock still applies: opening another file while a session is running does not
implement handoff into that Windows process. New exports carry the desktop and
display fixes; an already installed older package is not silently modified.
Legacy prefixes and old integration metadata need their own migration
qualification before replacing a user's existing baseline.
