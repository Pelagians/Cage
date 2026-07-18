# Cage Roadmap

Status: current planning index
Date: 2026-07-08

This file points to the active Cage roadmap documents and records explicit not-now items so scoped work does not silently expand.

## Current priority: consume the CFW prepared runtime

Source of truth: [ADR 0024 — CFW prepared-runtime provider](decisions/0024-cfw-prepared-runtime-provider.md). ADRs 0018–0023 preserve superseded approaches and evidence.

Phase 1 work:

1. Keep `chocolatey.py` as a small first-class module that validates package and runtime-profile intent.
2. Verify the detached CFW manifest before trusting archive or evidence hashes.
3. Bind source revision, installer/input digests, behavioral proofs, and the exact producer Wine image.
4. Safely replacement-seed the prepared prefix before all other modules, then perform only a bounded update.
5. Verify CFW-owned policy without reconstructing or mutating CLR, PowerShell, Synchro, or Chocolatey compatibility state.
6. Require a non-skipped package lifecycle before requested package installation and artifact export.

This serves Cage compatibility, but Cage remains non-blocking for the Nereus MVP. If this thread grows beyond roughly one week of effort, surface the company-level focus tradeoff before expanding scope.

## Active roadmap docs

- [Production Hardening Roadmap](production-hardening-roadmap.md) — runtime isolation, deterministic Chocolatey MVP path, module cache, capability sequencing.
- [Legacy Installer Debugging Backlog](legacy-installer-debugging-backlog.md) — generic legacy-installer primitives and deprecated debugging threads.

## Not-now register

### Additional Wine versions

Status: parked
Source: ADR 0024
Why parked: Phase 1 must first prove one immutable Wine 11 prepared runtime through the CFW producer and a non-skipped Cage consumer lifecycle.
Reactivation condition: Wine 11 passes all producer proofs, immutable release validation, Cage import, package lifecycle, bundle/OCI verification, and execution with one producer identity.
Expected shape when reactivated: CFW publishes separately proven Wine 9/10 artifacts with the same detached-manifest contract; Cage consumes them without adding version-specific compatibility logic.
