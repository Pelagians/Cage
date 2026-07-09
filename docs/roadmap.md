# Cage Roadmap

Status: current planning index
Date: 2026-07-08

This file points to the active Cage roadmap documents and records explicit not-now items so scoped work does not silently expand.

## Current priority: upstream Chocolatey-for-wine wrapper

Source of truth: [ADR 0019 — Upstream Chocolatey-for-wine wrapper](decisions/0019-upstream-chocolatey-for-wine-wrapper.md). ADR 0018 is superseded historical context.

Phase 1 work:

1. Wrap pinned/checksummed Chocolatey-for-wine and run upstream `ChoCinstaller_*.exe /s /q`.
2. Keep canonical `C:/ProgramData/chocolatey/bin/choco.exe` verification and diagnostic JSON before package installs.
3. Keep manifest-level `chocolatey`/`powershell-wrapper` mutual exclusion until capabilities land.
4. Keep `--module-cache-dir` for reusable module payloads and upstream installer cache.
5. Add SHA-256 verification to `powershell-wrapper` Codeberg downloads separately.

This serves Cage compatibility, but Cage remains non-blocking for the Nereus MVP. If this thread grows beyond roughly one week of effort, surface the company-level focus tradeoff before expanding scope.

## Active roadmap docs

- [Production Hardening Roadmap](production-hardening-roadmap.md) — runtime isolation, upstream Chocolatey wrapper, module cache, capability sequencing.
- [Legacy Installer Debugging Backlog](legacy-installer-debugging-backlog.md) — generic legacy-installer primitives and deprecated debugging threads.

## Not-now register

### Profile/shim layering for Chocolatey + WindowsPowerShell coexistence

Status: parked
Source: ADR 0019 / superseded ADR 0018 Phase 3
Why parked: requires a real recipe that needs both Chocolatey package installation and WindowsPowerShell-dependent installer behavior in the same prefix. Implementing it now would expand scope beyond the upstream Chocolatey wrapper.
Reactivation condition: first recipe requiring both `chocolatey` packages and WinPS-dependent installers.
Expected shape when reactivated: vendor a pinned/checksummed `profile.ps1` as a Cage asset with an upstream-sync policy and dot-source chain so Chocolatey-for-wine shim functions and Synchro wrapper functions can coexist.

### Pre-baked Chocolatey runtime/build image

Status: proposed, not current Phase 1
Why parked: deterministic module steps are needed first for provenance, failures, and capability boundaries.
Reactivation condition: deterministic Chocolatey module works and repeated bootstrap time becomes the dominant bottleneck.
