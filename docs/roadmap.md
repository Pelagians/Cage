# Cage Roadmap

Status: current planning index
Date: 2026-07-08

This file points to the active Cage roadmap documents and records explicit not-now items so scoped work does not silently expand.

## Current priority: deterministic Chocolatey-for-Wine fork validation

Source of truth: [ADR 0022 — Deterministic Chocolatey-for-Wine fork](decisions/0022-deterministic-chocolatey-fork.md). ADRs 0019–0021 preserve the failed alternatives and evidence.

Phase 1 work:

1. Keep `chocolatey.py` as a small first-class module that validates package intent and emits ordered build steps.
2. Verify the patched fork release and every transitive payload through Cage's content-addressed module cache.
3. Materialize a private per-prefix bootstrap work directory and run the fork with `CFW_OFFLINE=1`.
4. Require installer, settlement, canonical-file, readiness, feature-policy, and package-lifecycle gates before user packages.
5. Keep manifest-level `chocolatey`/`powershell-wrapper` mutual exclusion until capabilities land.
6. Iterate against the real container-builder lifecycle workflow until it passes.

This serves Cage compatibility, but Cage remains non-blocking for the Nereus MVP. If this thread grows beyond roughly one week of effort, surface the company-level focus tradeoff before expanding scope.

## Active roadmap docs

- [Production Hardening Roadmap](production-hardening-roadmap.md) — runtime isolation, deterministic Chocolatey MVP path, module cache, capability sequencing.
- [Legacy Installer Debugging Backlog](legacy-installer-debugging-backlog.md) — generic legacy-installer primitives and deprecated debugging threads.

## Not-now register

### Profile/shim layering for Chocolatey + WindowsPowerShell coexistence

Status: parked
Source: ADR 0022 / ADR 0018 Phase 3
Why parked: requires a real recipe that needs both Chocolatey package installation and WindowsPowerShell-dependent installer behavior in the same prefix. Implementing it now would expand scope beyond the deterministic Chocolatey MVP path.
Reactivation condition: first recipe requiring both `chocolatey` packages and WinPS-dependent installers.
Expected shape when reactivated: vendor a pinned/checksummed `profile.ps1` as a Cage asset with an upstream-sync policy and dot-source chain so Chocolatey-for-wine shim functions and Synchro wrapper functions can coexist.

### Pre-baked Chocolatey runtime/build image

Status: proposed, not current Phase 1
Why parked: deterministic module steps are needed first for provenance, failures, and capability boundaries.
Reactivation condition: deterministic Chocolatey module works and repeated bootstrap time becomes the dominant bottleneck.
