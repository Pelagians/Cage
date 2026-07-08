# Cage Roadmap

Status: current planning index
Date: 2026-07-08

This file points to the active Cage roadmap documents and records explicit not-now items so scoped work does not silently expand.

## Current priority: deterministic PowerShell and Chocolatey Phase 1

Source of truth: [ADR 0018 — Deterministic PowerShell and Chocolatey capabilities](decisions/0018-deterministic-powershell-chocolatey-capabilities.md).

Phase 1 work:

1. Rebuild `chocolatey` so it no longer executes `ChoCinstaller_*.exe`.
2. Make PowerShell 7 engine installation a shared deterministic component.
3. Keep manifest-level `chocolatey`/`powershell-wrapper` mutual exclusion until capabilities land.
4. Add SHA-256 verification to `powershell-wrapper` release downloads.
5. Add `--module-cache-dir` for reusable module payloads.

This serves Cage compatibility, but Cage remains non-blocking for the Nereus MVP. If Phase 1 grows beyond roughly one week of effort, surface the company-level focus tradeoff before expanding scope.

## Active roadmap docs

- [Production Hardening Roadmap](production-hardening-roadmap.md) — runtime isolation, deterministic Chocolatey, module cache, capability sequencing.
- [Legacy Installer Debugging Backlog](legacy-installer-debugging-backlog.md) — generic legacy-installer primitives and deprecated debugging threads.

## Not-now register

### Profile/shim layering for Chocolatey + WindowsPowerShell coexistence

Status: parked
Source: ADR 0018 Phase 3
Why parked: requires a real recipe that needs both Chocolatey package installation and WindowsPowerShell-dependent installer behavior in the same prefix. Implementing it now would expand scope beyond the deterministic Phase 1 rebuild.
Reactivation condition: first recipe requiring both `chocolatey` packages and WinPS-dependent installers.
Expected shape when reactivated: vendor a pinned/checksummed `profile.ps1` as a Cage asset with an upstream-sync policy and dot-source chain so Chocolatey-for-wine shim functions and Synchro wrapper functions can coexist.

### Pre-baked Chocolatey runtime/build image

Status: proposed, not current Phase 1
Why parked: deterministic module steps are needed first for provenance, failures, and capability boundaries.
Reactivation condition: deterministic Chocolatey module works and repeated bootstrap time becomes the dominant bottleneck.
