# ADR 0024: CFW prepared runtime is the sole Chocolatey compatibility provider

- Status: Accepted
- Date: 2026-07-17
- Owner: Noah Giroux (CTO)
- Supersedes: ADR 0023
- Reversibility: Medium before the first CFW runtime release
- Source of truth: this record and the pinned CFW release manifest

## Context

ADR 0023 assigned PowerShell, Synchro wrappers, the root profile, and related Wine policy to Cage. That was a transitional response to failures in the old CFW bootstrap. It conflicts with the current architecture: CFW owns Windows compatibility and Cage owns orchestration.

The initial prepared-runtime consumer removed much of Cage's WMF/GAC/CLR reconstruction, but retained experimental PowerShell providers and AIK/MSCoree diagnostic workflows. Its lifecycle job also reported success while skipping all real work because no released runtime was pinned.

## Decision

For the Chocolatey module, CFW's immutable prepared-prefix runtime is the exclusive provider of:

- Wine/.NET/CLR compatibility state;
- PowerShell and its root profile;
- Synchro x64/x86 wrappers;
- canonical Chocolatey bootstrap and feature policy;
- CFW registry and command-adapter behavior.

Cage performs only:

1. complete detached-manifest, runtime-evidence, and archive verification;
2. replacement seeding of an empty build prefix;
3. declared Wine-image and producer-environment verification, propagation, and bounded `wineboot -u`;
4. requested package install/uninstall and application lifecycle checks;
5. final artifact export.

For this phase, “prefix ownership” is split explicitly: CFW constructs the
initial compatibility prefix; Cage creates an empty destination, replacement-
seeds the verified artifact, selects the exact producer Wine image before any
Wine command, performs the bounded update/lifecycle, and owns the resulting
application prefix and artifact. Cage does not reconstruct or initialize the
Windows compatibility state itself.

Cage's Chocolatey CI must not be green because the real lifecycle was skipped. Until a runtime is pinned, runtime resolution fails the workflow so the lifecycle is visibly blocked rather than reported as successful validation.

## Consequences

- ADR 0023 is deprecated and must not guide implementation.
- Cage-owned PowerShell/Synchro experimental providers and one-off AIK/MSCoree diagnostics are removed from this integration branch.
- The Chocolatey runtime artifact schema includes the detached manifest and its digest, not only archive/evidence URLs.
- The resolved runtime artifact is serialized into the bundle manifest even when it came from Cage's built-in default, so the bundle always carries its trust root.
- CFW declares the post-bootstrap runtime environment. Cage validates it against the detached manifest and propagates it unchanged through build, graph, bundle, run, and OCI export. Recipe `launch.env` may not collide with producer-owned keys, and bundle verification binds the complete launch contract back to the serialized manifest.
- The consumer validates the manifest bindings instead of trusting separately supplied hashes.
- Runtime-profile values are validated before build-script generation and transported as encoded data, not interpolated shell fragments.
- Archive members are validated and extracted into temporary storage; the destination prefix is replaced only after paths, links, types, sizes, and required files pass.
- A CFW-backed recipe cannot also select `runtime.runner`; Wine identity comes exclusively from the exact producer image digest.
- A recipe contains exactly one Chocolatey module so the prepared prefix is materialized once.
- The first pinned CFW release activates a mandatory non-skipped lifecycle proof.

## Rejected alternatives

- Keeping standalone PowerShell compatibility in Cage “for diagnostics” is rejected because it preserves the old ownership and creates a second implementation.
- Allowing evidence and archive hashes without the detached manifest is rejected because it does not bind provenance to the exact release artifact.
- Applying a CFW installer to a Cage-initialized prefix is deferred for Phase 1.
  It is a valid future interface, but it would create a second producer path
  before the prepared-prefix path has passed once. Revisit only with evidence
  that replacement seeding cannot survive the bounded Cage update lifecycle.

## Review trigger

Review if Cage needs a non-Chocolatey PowerShell module with a product requirement independent of CFW. Such a capability must be proposed separately and must not mutate a CFW-backed prefix.
