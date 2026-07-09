# Cage Documentation

## Quick Start

- [README](../README.md) - Installation and usage
- [Architecture](architecture.md) - High-level design
- [Container Architecture](container-architecture.md) - OCI image structure

## Specifications

- [Spec v0](spec-v0.md) - Recipe schema and module system
- [Reference Study](reference-study.md) - Comparison with BlueBuild, etc.

## Decisions

Architecture Decision Records (ADRs) in chronological order:

1. [Boundaries: Artifacts vs Runtime](decisions/0001-boundaries-artifacts-runtime.md)
2. [Ramalama-like Runtime Model](decisions/0002-ramalama-like-runtime-model.md)
3. [Application-First Recipes, Artifacts, State](decisions/0003-application-first-recipes-artifacts-runtime.md)
4. [UMU-Proton-GE Runtime Stack](decisions/0004-umu-proton-ge-runtime-stack.md)
5. [Runner Version Aliases and Pinning](decisions/0005-runner-version-aliases-and-pinning.md)
6. [Runnable Application OCI Export](decisions/0006-runnable-application-oci-export.md)
7. [Local Artifact Index and App Name Resolution](decisions/0007-local-artifact-index-and-app-name-resolution.md)
8. [OCI Digest and Image Verification](decisions/0008-oci-digest-and-image-verification.md)
9. [Kubernetes Manifest Export](decisions/0009-kubernetes-manifest-export.md)
10. [Compatibility Policy Layer](decisions/0010-compatibility-policy-layer.md)
11. [Source Integrity and Compat Evidence](decisions/0011-source-integrity-and-compat-evidence.md)
12. [Real Compat Evidence and Corpus](decisions/0012-real-compat-evidence-and-corpus.md)
13. [BYO Files and Office Suite Primitives](decisions/0013-byo-files-and-office-suite-primitives.md)
14. [Private Recipes and Suite Runtime UX](decisions/0014-private-recipes-and-suite-runtime-ux.md)
15. [Downloadable Wine Runner Cache](decisions/0015-downloadable-wine-runner-cache.md)
16. [Container-Mounted Runner Execution](decisions/0016-container-mounted-runner-execution.md)
17. [BlueBuild-Style Build Modules](decisions/0017-bluebuild-style-build-modules.md)
18. [Deterministic PowerShell and Chocolatey Capabilities](decisions/0018-deterministic-powershell-chocolatey-capabilities.md) — refined
19. [Upstream Chocolatey-for-wine Wrapper](decisions/0019-upstream-chocolatey-for-wine-wrapper.md) — superseded
20. [Deterministic Chocolatey-for-wine MVP Reconstruction](decisions/0020-deterministic-chocolatey-for-wine-mvp.md)

## Roadmaps

- [Cage Roadmap](roadmap.md)
- [Legacy Installer Debugging Backlog](legacy-installer-debugging-backlog.md)
- [Production Hardening Roadmap](production-hardening-roadmap.md)

## VIC Integration

- [VIC Boundary](vic-boundary.md) - How Cage fits into VIC ecosystem
