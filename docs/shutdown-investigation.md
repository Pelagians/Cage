# Wine shutdown investigation

This investigation keeps failed trials as failures. A GUI disappearing, an
application log saying `exit code: 0`, or a later successful retry is not sufficient
to qualify a clean Wine shutdown. The 120-second GUI shutdown deadline, zero exit
requirement, quiescence checks, and migration/rollback assertions remain in force.

## Cases being distinguished

- The original ARM FEX-2610 payload has a previously reproduced shutdown deadlock:
  a peer can die while holding the JIT lookup-cache writer lock, and FLS/DLL cleanup
  on the remaining thread can block compiling another callback. The `cage1`
  termination guard drains translator locks before Wine terminates peer threads.
  Historical packages and rollback targets retain their exact original payload;
  running a retained FEX-2610 package does not implicitly install that repair.
- Runtime migration runs `39933054117` and `39994050603` timed out while using
  that original payload. The latter retained only one application thread, waiting
  in a native futex after Sumatra logged exit zero. Its truncated map/stack evidence
  is insufficient to attribute the precise wait to the previously identified lock.
- Onboarding runs also returned 247 under the repaired runtime: run
  `39994050734` failed during the initial v0 launch; an earlier `cb45` trial failed
  during adoption under the v1 helper. Neither has signal-sender evidence. These
  must not be attributed solely to the historical manager or original translator.
- The repaired-runtime Notepad++ OCI timeout is a separate unresolved case. Its
  original artifact collection failed, so its retained log cannot distinguish
  application, Wine-server, container-init and Podman-client waits.

The pinned Wine 11.20 [Unix exit wrapper](https://github.com/wine-mirror/wine/blob/wine-11.20/dlls/ntdll/unix/server.c)
closes its Wine-server socket before calling the C library `exit()`. The
[server process implementation](https://github.com/wine-mirror/wine/blob/wine-11.20/server/process.c)
starts a bounded process-death timer and can issue SIGKILL if the Unix process
remains alive. This is one concrete potential source of a post-exit kill, not a
confirmed explanation for the historical 247 results. Other signal sources and
memory pressure remain possible until a failing trial records them.

## Reproduction and evidence

Commit `64928ff` adds an opt-in mode to the existing onboarding workflow:

```sh
gh workflow run application-onboarding.yml \
  --ref codex/safe-export-updates -f shutdown_relaunches=25
```

It runs the container matrix only. Each of the existing persistent-container,
standalone OCI and trusted OCI proofs repeats its initial package session 25
additional times before proceeding through the ordinary migration/update,
relaunch and rollback assertions. ARM persistent-container and OCI initial
sessions use the sealed historical v0 helper. Every iteration performs a real
Save As, checks document bytes and the retained preference, and must close
normally before the next iteration. The first failure stops that proof.

`CAGE_TEST_TRACE_SHUTDOWN=1` is restricted to CI and private container proofs.
After the saved document is validated, the observer finds the container by its
exact private state mount and attaches to that container's application and Wine
server. It records process and signal syscalls around close. It does not attach
to the Podman client or send diagnostic signals to Wine. The observer has a
separate process group and is detached before timeout debugger collection.
Missing or ambiguous ownership, unavailable tracing, and failed attachment are
errors rather than silently untraced passes. Runtime images and application
exit statuses are not changed by this mode.

The follow-up observer also records each owned process's name, host PID and
`NSpid` mapping. Trace-line prefixes use host PIDs, while signal syscall arguments
use container PIDs. These must be correlated before identifying a signal victim.

Failure diagnostics retain up to 1 MiB of each process's memory-map text, because
ARM64EC's numerous low PE mappings previously displaced the high Unix library
mappings needed to resolve its futex program counter. The collector continues
to exclude prefixes, documents, package caches, symlinks and private keys.

## Native Asahi observation, 2026-10-23

A fresh private v0 state was exercised through the mounted, sealed legacy
SumatraPDF AppImage's `AppRun` on an Apple M1 with 16 KiB pages and a private X11
server. An ancestor `strace` recorded its owned process tree. All 25 sessions
saved the exact PDF bytes, retained the selected toolbar preference and exited
zero. Close-to-exit times were 0.542–1.253 seconds (median 0.746 seconds). No
SIGKILL appeared in the 2,484 per-process/thread traces.

The package SHA-256 was
`926fcf68d9d5d7c4b76a81147c3fbd76e0a33b4906479ebf1a1e329294c79dc3`, with target
`appimage-wine-arm64ec-11.20-fex-2610-cage1-aarch64`. Records are retained under
`.cage/shutdown-investigation-ready/`. An earlier diagnostic attempt passed its
first session but missed the Save As readiness window in session two; it is
retained separately under `.cage/shutdown-investigation/` and is not counted as a
successful stress run. The corrected probe uses the existing bounded Save As
readiness behavior.

These are diagnostic observations, not a new runtime repair, installed-package
update or full installed migration qualification. No installed app was replaced.
Private diagnostic Windows files were extent-shared only after their processes
stopped; the kernel verified equal contents and every independent file remains.

The installed-state comparison checked 25,112 existing entries. Only the user's
Notepad++ AppImage `config.xml`, `system.reg` and `user.reg` differed; the user
confirmed using or closing Notepad++ during the private Sumatra test. Those
current files were retained without restoration. All other recorded entries,
including documents and rollback data, matched, and the normal Notepad++ Flatpak
commit was unchanged. The private receipt is
`.cage/asahi-installed-qualification/shutdown-investigation-user-state-comparison.json`.

## Focused CI result

[Run 40011309865](https://github.com/Pelagians/Cage/actions/runs/40011309865), at
`64928ff`, passed all 182 traced sessions: 90 on x86_64 and 92 on ARM64. The ARM
persistent-container and OCI cases each include 26 initial v0 sessions followed
by adoption, update, relaunch and rollback. Trusted OCI uses the current manager.
All recorded document hashes and preservation assertions passed; four retained
release signatures verified independently against the bound source revision.
Both initially attached application and server processes exited zero in every
trace. These runners use 4 KiB pages; the native 16 KiB observation is separate.

Successful traces contain Wine-server SIGKILL calls to other processes during
cleanup: 720 calls across the x86_64 trials and 644 across ARM64. No traced
application/server was reported killed by a signal. This confirms that finding
a SIGKILL syscall alone cannot diagnose the historical exit 247. The private
records and independent summaries are under
`.cage/asahi-installed-qualification/shutdown-focused-64928ff/`.

The unit suite passed 611 tests and 214 subtests. Three tests initially blocked by
sandbox packaging/socket permissions passed when rerun with their ordinary local
fixtures. The subsequent PID-mapping addition passed all 11 diagnostic tests;
that addition is not part of run `40011309865`.

The ordinary [migration](https://github.com/Pelagians/Cage/actions/runs/40011294723),
[onboarding](https://github.com/Pelagians/Cage/actions/runs/40011294763) and
[update/rollback](https://github.com/Pelagians/Cage/actions/runs/40011294700) runs
have passed their container cells on both architectures and their x86_64 desktop
cells. ARM desktop jobs remain in progress. Downloaded migration/onboarding
records from the completed cells independently verified 104 GUI sessions,
document preservation and 16 release signatures; these are partial matrix
results, not completed ARM desktop qualification.

No new production shutdown repair is claimed. The remaining repaired-runtime
failures did not recur in this bounded investigation. A future failed trace must
identify the affected process and sender; a timeout additionally needs the
retained native/Windows stack. The original payload remains an immutable
historical target, and the existing `cage1` repair does not alter it retroactively.
