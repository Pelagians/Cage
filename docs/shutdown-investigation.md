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

The ordinary [migration](https://github.com/Pelagians/Cage/actions/runs/40011294723)
and [onboarding](https://github.com/Pelagians/Cage/actions/runs/40011294763) runs at
`64928ff` subsequently passed all four matrix cells, including ARM desktop.
Downloaded records independently verified all 14 cases and 70 GUI sessions for
runtime migration, and all 14 cases and 76 GUI sessions for onboarding. Each
matrix verified document/settings preservation, rollback identities and 12
retained release signatures. The concurrent
[update/rollback run](https://github.com/Pelagians/Cage/actions/runs/40011294700)
was cancelled by the superseding `707e69a` push; it is not counted as a pass.

## Regression results at `707e69a`

The superseding
[update/rollback run 40015101147](https://github.com/Pelagians/Cage/actions/runs/40015101147)
passed all four matrix cells. Its 14 cases and 12 retained release signatures
verified independently, including desktop MIME handling, read-only original
protection, Save As, selected-file save/relaunch and DPI preservation through
update and rollback on both architectures. The ordinary
[AppImage proof](https://github.com/Pelagians/Cage/actions/runs/40015101288),
[x86_64 Flatpak proof](https://github.com/Pelagians/Cage/actions/runs/40015101222)
and [ARM Wine/FEX proof](https://github.com/Pelagians/Cage/actions/runs/40015101067)
also passed. ARM AppImage's clean Ubuntu and Fedora consumer records both show
save/relaunch using the same state generation without host Wine or Python.
These CI runners use 4 KiB pages; installed Asahi qualification remains separate.

The final
[onboarding run 40015101040](https://github.com/Pelagians/Cage/actions/runs/40015101040)
also passed all four matrix cells, including both ARM desktop formats.
Independent verification covered all 14 cases, 76 GUI sessions and 12 retained
release signatures, with exact document hashes, retained preferences and
legacy-adoption/update/rollback generation identities. All remaining desktop
checks are complete. ARM legacy-onboarding fixtures use the repaired `cage1`
runtime; the runtime-migration baseline below retains the original FEX payload.

The ARM container cell of
[runtime migration run 40015101138](https://github.com/Pelagians/Cage/actions/runs/40015101138)
failed in standalone OCI's `1-original` session, before migration or the candidate
runtime started. Its preceding persistent-container proof passed all five
sessions. Sumatra saved the expected PDF and logged `Exiting with exit code: 0`,
but its process remained alive beyond the unchanged 120-second shutdown deadline.
The container was still running and reported `OOMKilled: false`.

Both desktop matrix cells passed Flatpak and AppImage migration, trusted delivery
and rollback. The x86_64 container cell also passed. Independently verified
successful records cover 12 cases, 60 GUI sessions and 10 retained release
signatures. The overall workflow remains failed: ordinary ARM OCI failed its
initial session, and trusted ARM OCI was not reached. The partial verification
receipt explicitly records both unqualified cases rather than reporting a full
matrix pass.

The failing target is the original
`wine-arm64ec-11.20-fex-2610-aarch64`, not the candidate
`wine-arm64ec-11.20-fex-2610-cage1-aarch64`. The retained process tree shows the
launcher waiting for the application, whose only remaining thread is waiting in
a futex. Its native return address resolves to `NtWaitForAlertByThreadId+0x144`;
a saved Windows return address resolves to `RtlWaitOnAddress+0x1f4`. The captured
stack does not establish the guest wait address or FEX lock owner, so this trial
cannot yet be attributed to the precise translator mutex diagnosed previously.
The evidence is retained under
`.cage/asahi-installed-qualification/runtime-migration-arm-failure-707e69a/`.

The strict qualification gate remains in force, as explicitly requested after
this failure was reported. Historical runtime payloads and rollback eligibility
are unchanged. The failed trial remains a failure; no retry, longer deadline,
success normalization or recovery-only runtime policy substitutes for diagnosis.
The next diagnostic reproduction needs the owned OCI process's Windows/FEX stack
and guest wait address alongside the native stack and thread ownership. A normal
shutdown on another trial does not establish the cause or qualify this failure.

This CI follow-up did not launch or replace installed applications. A fresh
preservation baseline includes the user's previously acknowledged Notepad++
changes. All 59,051 recorded entries subsequently matched, with no added or
changed paths and the normal Notepad++ Flatpak commit unchanged. The private
receipt is
`.cage/asahi-installed-qualification/arm-regression-707e69a-protected-after.json`.

No new production shutdown repair is claimed. The remaining repaired-runtime
failures did not recur in this bounded investigation. A future failed trace must
identify the affected process and sender; a timeout additionally needs the
retained native/Windows stack. The original payload remains an immutable
historical target, and the existing `cage1` repair does not alter it retroactively.

## Original OCI diagnosis, 2026-10-23

A private Asahi OCI reproduction used the original carrier and a read-only
sealed Sumatra 3.6 bundle, with fresh private state and an authenticated private
X11 display. It completed 69 normal save/close sessions, then failed session 70
at the unchanged 120-second deadline. The saved PDF matched the original bytes
and Sumatra logged exit zero. The failed container was retained for live capture;
its later diagnostic cleanup is not counted as successful shutdown.

The only remaining application thread was in `RtlWaitOnAddress`. Wine's saved
ARM syscall frame exposed the FEX stack, with return addresses resolving to
`WaitOnAddress+0x24`, `WritePriorityMutex::lock_shared+0x110`,
`LookupCache::FindBlock+0x84` and `ContextImpl::CompileBlock+0x88`. The main Windows
stack also contains `RtlProcessFlsData`, `LdrShutdownProcess` and
`RtlExitUserProcess`. A direct read of the lookup-cache mutex at
`0x7ff4e0130080` returned `0xc0000000`: FEX's pinned
[writer-owned and reader-waiter bits](https://github.com/FEX-Emu/FEX/blob/14c92681f4d62cf84d901460e0358de09c8847a7/FEXCore/include/FEXCore/Utils/WritePriorityMutex.h).
This confirms the stranded-writer defect in the original OCI runtime during
FLS/JIT cleanup. The dump does not identify the departed writer's thread ID.

Expanded CI diagnostics captured the same FEX return-address sequence on a
4 KiB ARM runner in
[job 120666225563](https://github.com/Pelagians/Cage/actions/runs/40027188808/job/120666225563),
at `b1a275c`. Ordinary container and OCI migration proofs passed; trusted OCI
failed in `6-relaunch` after rollback restored the original runtime. Its two
retained release signatures verified against that source revision and identify
the original and guarded targets separately. This is another failed trial, not
a failure in the guarded candidate. The CI dump retains the same wait path and
expected writer bits; the direct live mutex read above is from Asahi.

The repair is the existing pinned `fex-2610-cage1` termination guard: drain
translator writers before Wine terminates peer threads, then release the
barrier before final cleanup. It requires its own runtime identity. Changing
the original DLL under an old image identity, retiring its launch eligibility,
or masking its shutdown result would violate this investigation's strict gate.

The collector now retains Wine 11.20's bounded saved ARM context, Windows SP/FP
stack words and wait-target words after an owned application failure. These
reads do not change Wine, timeouts or application exit codes. The existing
runtime-migration workflow can stress the exact original OCI target separately:

```sh
gh workflow run runtime-migrations.yml \
  --ref codex/safe-export-updates \
  -f original_oci_relaunches=25 -f container_stress_relaunches=0
```

This adds 25 initial save/close sessions, stops at the first failure, and retains
the ordinary migration, relaunch, rollback and trusted-delivery assertions.
[Focused run 40027445937](https://github.com/Pelagians/Cage/actions/runs/40027445937)
passed its six container/OCI cases: 55 GUI sessions and four independently
verified signatures. Its success is a bounded observation of an intermittent
defect; the independent Asahi and ordinary CI failures remain failed.

Private reproduction records, guest-stack captures, symbolized return addresses
and recovery proofs are under `.cage/original-oci-shutdown/`. Runtime repair is
validated through an explicitly allowed migration on a separate copy of the
failed state, retaining the forensic original and its rollback runtime.

A separate carrier layer applies the existing verified guard to the original
carrier and declares the guarded target's own identity. Cage's ordinary builder
and runtime-migration recipe helper produced the sealed candidate; no DLL was
rewritten in the failed prefix. On an independent reflinked copy of that state,
the explicit update and subsequent save/close/relaunch sequence passed 100
guarded sessions. A further real GUI Save As wrote a PDF inside the prefix,
followed by exact-original-runtime rollback, guarded re-upgrade and relaunch.
All 104 recovery sessions exited zero before the unchanged deadline and retained
the selected toolbar preference and exact document bytes. The original external
documents remain unchanged, and the internal PDF survived rollback and
re-upgrade. Four generations remain, including the unchanged original prefix.
The forensic source-state digest and original DLL SHA-256 also remain unchanged.

This native 16 KiB proof mounts sealed bundles read-only in verified OCI carriers;
it establishes failed-prefix recovery and rollback behavior separately from
standalone image distribution and installed desktop qualification. An initial
private attempt failed before Wine launch because of a Podman storage lookup;
another recovery harness attempt collided with existing Save As filenames.
Both are retained as unqualified harness attempts. The corrected driver uses
unique filenames and rejects pre-existing outputs before invoking Save As.

The final unit suite passed 614 tests and 214 subtests. A fresh installed-state
comparison checked 59,051 existing entries with no changed or added paths, and
the normal Notepad++ Flatpak commit is unchanged. No installed application was
launched or replaced. The private receipts are `verified-recovery.json`,
`verified-focused-ci.json` and `protected-after.json` in the directory above.

No additional translator patch is justified by this diagnosis: `cage1` already
contains the repair. Its safe application is an explicit, identified runtime
migration. The original immutable runtime retains the defect, its failed trials
remain failed, and its strict launch/rollback qualification is unchanged.

## CI reruns at `1e1677c`

The [update/rollback rerun](https://github.com/Pelagians/Cage/actions/runs/40031256547)
passed all four matrix cells. Independent verification covers 14 cases and 12
release signatures, including settings, documents, retained generations,
desktop file access and DPI through update and rollback on both architectures.
The [AppImage proof](https://github.com/Pelagians/Cage/actions/runs/40031256597),
[Flatpak proof](https://github.com/Pelagians/Cage/actions/runs/40031256591) and
[ARM Wine/FEX proof](https://github.com/Pelagians/Cage/actions/runs/40031256575)
also passed. The ARM proof's container and Flatpak records independently verify
save/relaunch, unchanged seed state and the guarded `cage1` target identity.

The [onboarding rerun](https://github.com/Pelagians/Cage/actions/runs/40031256525)
finished successfully in all four matrix cells, including ARM Flatpak and
AppImage. Independent verification covers all 14 cases, 76 GUI sessions and 12
release signatures, with exact document hashes, retained toolbar preferences,
legacy adoption and update/rollback generation identities. The preceding
[onboarding run at `b1a275c`](https://github.com/Pelagians/Cage/actions/runs/40027188814)
also verified separately with the same complete coverage. ARM onboarding's
legacy fixtures use the guarded runtime; they do not qualify the original FEX
runtime used below.

The [runtime-migration rerun](https://github.com/Pelagians/Cage/actions/runs/40031256587)
remains failed. Both desktop cells and x86_64 containers passed; their retained
records independently verify 11 cases, 55 GUI sessions, ten release signatures
and different original/candidate runtime payloads. These are partial results,
not full matrix acceptance.

The [ARM container job](https://github.com/Pelagians/Cage/actions/runs/40031256587/job/120679778894)
again timed out at the unchanged 120-second deadline in trusted OCI
`6-relaunch`, after rollback restored the original runtime. Its log shows the
preceding ordinary container/OCI trials completed. Evidence collection ran,
but GitHub's artifact creation endpoint timed out on all five transport
attempts, so this job has no retained downloadable proof artifact. The raw job
log is preserved locally. The phase matches the earlier original-runtime
failure; without its missing dump, this trial does not independently establish
the exact lock state diagnosed above. It remains a failed trial, and neither
its earlier sessions nor signatures are included in the independently verified
11-case subtotal.

The download review retained only small proof records, signatures and logs;
package binaries were not downloaded. Verification receipts are
`verified-updates-1e1677c.json`, `verified-runtime-migrations-1e1677c.json` (explicitly
partial), `verified-onboarding-1e1677c.json` and `verified-arm-fex-1e1677c.json` under
`.cage/asahi-installed-qualification/`. The failed job log is
`.cage/original-oci-shutdown/ci-1e-arm.log`.

This review did not launch or modify installed applications, settings,
documents or rollback generations. No production runtime change is supported
by these reruns: the existing identified `cage1` migration remains the repair,
and the original runtime's strict qualification remains red. No application
trial was retried, timeout relaxed, payload substituted or failure masked.
These CI proofs use 4 KiB runners and private X11 displays; they do not replace
the separately recorded Asahi/16 KiB recovery or installed desktop proofs.

## Approved repaired rollback

The user subsequently approved explicit repaired rollback with a new runtime
identity, retaining the exact original for recovery. The new `rollback-repair`
operation implements that choice through the shared generation transaction.
Exact `rollbackRepairs` rules, executable/profile checks and operation-specific
signed evidence authorize the guarded package; ordinary rollback and the
original failed qualification remain unchanged. See
[the operation and qualification requirements](runtime-migrations.md#explicit-repaired-rollback).

A new private Asahi/16 KiB proof used a reflinked copy of the retained four-
generation investigation state. One normal guarded session changed the current
toolbar preference, then repaired rollback restored the original preference in
a fresh guarded generation. All 25 subsequent real PDF save/close/relaunch
sessions exited normally before the unchanged 120-second deadline. The source
original runtime identity remains recorded in `rollbackRepair`; the active
identity names the guarded runtime and new package contract. Newer preferences
remain recoverable, and the existing internal PDF and external document bytes
are preserved. These 27 sessions mount sealed bundles read-only in the verified
guarded OCI carrier; they are separate from new standalone image distribution
or installed Flatpak/AppImage qualification.

The full suite passed 627 tests and 227 subtests, including actual subprocess
state transactions, unsafe-source/storage refusal, deployment recovery, real
Ed25519 signatures and retained repair history without sequence rewind.
The workflow has a separate explicit repair mode for the pending 4 KiB and
desktop proofs. Its default strict original-runtime gate is not replaced.
Private build, native GUI and preservation records are under
`.cage/repaired-rollback/`. No installed application was upgraded or launched.
Independent receipts `verified-native.json` and `protected-after.json` confirm
the native invariants and all 59,051 installed-state entries unchanged, with no
added paths and the normal Notepad++ Flatpak commit unchanged. The new private
build and repaired prefix share only kernel-verified identical Windows extents;
no original artifact, generation, document or differing byte was removed.
