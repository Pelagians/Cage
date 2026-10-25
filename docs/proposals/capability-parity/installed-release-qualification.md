# Installed v2 release qualification

This follow-up qualifies the signed installed lifecycle independently of the
producer-candidate runtime tests. The `installed-release-parity` job in
`capability-parity.yml` has independent native Ubuntu 24.04 x86_64/X11 cells for
OCI, Flatpak and AppImage. Results must be read from the exact commit's retained
`installed/installed-release.json`; adding the harness is not a qualification pass.

## Scope and signing boundary

The installed probe requests folders, optional networking and X11. It requests
**no devices**. The existing nine All Devices/denial/rebinding runtime scenarios
remain in the separate runtime job. Their owned synthetic null-device alias
cannot satisfy controlled Windows device detection and physical reconnect.
The installed proof records device/hotplug cases as blocked. The production
v2 signing gate is unchanged. No MyHarmony release is issued by these tests.

The producer runs its original package, a permission-reason-only recipe revision,
and the original again, asserting a normal window, native child boundary,
persistent user preference and advancing prefix counter. Only the owned fixture
bundle is copied and resealed for this policy revision; ordinary bundle,
export, signature and consumer verification remain in force. Original seed and
bundle inventories must remain unchanged. The revision changes the reviewed
capability contract while preserving the effective requested scope and state
compatibility. This does not qualify arbitrary runtime or application migrations.

## Consumer checks

Each adapter uses a fresh app ID and a disposable consumer home, XDG directories,
Flatpak installation and release cache. The publisher key stays outside uploaded
evidence; the public key, manifests, detached signatures and proof records are
retained. The consumer uses the public CLI to:

1. Fresh-install a signed release with explicit contract acceptance, then execute
   its actual installed desktop `Exec` command with a Unicode-path document.
2. Refuse the changed contract without acceptance; accept, update and relaunch it
   without selecting a new prefix or replacing recovery data.
3. Revoke optional networking, roll back to the exact original release, require
   review of that historical contract, and observe that revocation still applies.
4. Preview a folder replacement, apply its native Flatpak delta as the independent
   test operator, then verify/adopt the binding. Cage never writes native overrides.
5. Recover and relaunch; reject a stale sequence. Verify the release high-water
   mark, exact active/previous digests, saved preference/document, unchanged
   generation record, same active prefix and unchanged retained recovery copy.
6. Return to the original producer environment and explicitly adopt its verified
   existing v2 package/state. The producer state inventory must remain unchanged.

Desktop execution expands the installed entry's `%F` directly without a shell.
It tests that entry's actual command and document forwarding; it does not claim
that a human clicked a desktop menu or that the desktop selected a MIME handler.
Flatpak native CLI edits exercise the same effective policy surface as Flatseal;
they do not qualify Flatseal UI interaction or every concurrent-edit/crash case.
No physical device command or USB synchronization occurs. This remains CI desktop
proof, not installed Asahi/Wayland or MyHarmony login/service qualification.

Failures retain their diagnostic records and owned test state. No existing user
prefix, native override, trust record or recovery artifact is reset or adopted.
The only host device mutation remains the fresh owned null alias from the
runtime harness, never physical hardware. SDK cleanup is confined to the
throwaway GitHub-hosted runner.
