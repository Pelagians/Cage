# Cage Roadmap

Status: current planning index
Date: 2026-07-08

This file points to the active Cage roadmap documents and records explicit not-now items so scoped work does not silently expand.

## Current priority: deterministic Chocolatey-for-wine MVP path

Source of truth: [ADR 0020 — Deterministic Chocolatey-for-wine MVP reconstruction](decisions/0020-deterministic-chocolatey-for-wine-mvp.md). ADR 0019 is superseded by real-build evidence; ADR 0018 is refined historical context.

Phase 1 work:

1. Rebuild `chocolatey` as sequential upstream-derived steps rather than trusting `ChoCinstaller_*.exe /s /q` as the success boundary.
2. Keep pinned/checksummed upstream Chocolatey-for-wine release data, c_drive flattening, Chocolatey nupkg extraction, dedicated .NET x86/x64 MSI installs gated by native CLR marker presence, native CLR policy, native promotion, diagnostics, and canonical `choco.exe` package installs.
3. Apply upstream Chocolatey feature policy before package installs: disable `powershellHost`, enable `allowGlobalConfirmation`.
4. Keep manifest-level `chocolatey`/`powershell-wrapper` mutual exclusion until capabilities land.
5. Keep `--module-cache-dir` for reusable module payloads and upstream installer cache.
6. Add SHA-256 verification to `powershell-wrapper` Codeberg downloads separately.

This serves Cage compatibility, but Cage remains non-blocking for the Nereus MVP. If this thread grows beyond roughly one week of effort, surface the company-level focus tradeoff before expanding scope.

## Active roadmap docs

- [Production Hardening Roadmap](production-hardening-roadmap.md) — runtime isolation, deterministic Chocolatey MVP path, module cache, capability sequencing.
- [Legacy Installer Debugging Backlog](legacy-installer-debugging-backlog.md) — generic legacy-installer primitives and deprecated debugging threads.

## Not-now register

### Profile/shim layering for Chocolatey + WindowsPowerShell coexistence

Status: parked
Source: ADR 0020 / ADR 0018 Phase 3
Why parked: requires a real recipe that needs both Chocolatey package installation and WindowsPowerShell-dependent installer behavior in the same prefix. Implementing it now would expand scope beyond the deterministic Chocolatey MVP path.
Reactivation condition: first recipe requiring both `chocolatey` packages and WinPS-dependent installers.
Expected shape when reactivated: vendor a pinned/checksummed `profile.ps1` as a Cage asset with an upstream-sync policy and dot-source chain so Chocolatey-for-wine shim functions and Synchro wrapper functions can coexist.

### Pre-baked Chocolatey runtime/build image

Status: proposed, not current Phase 1
Why parked: deterministic module steps are needed first for provenance, failures, and capability boundaries.
Reactivation condition: deterministic Chocolatey module works and repeated bootstrap time becomes the dominant bottleneck.
