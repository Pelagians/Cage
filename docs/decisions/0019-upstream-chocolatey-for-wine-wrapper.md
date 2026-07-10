# 0019. Upstream Chocolatey-for-wine wrapper

Status: historical; superseded by [0022. Deterministic Chocolatey-for-Wine fork](0022-deterministic-chocolatey-fork.md)
Date: 2026-07-09
Owner: Noah Giroux / CTO
Supersedes: [0018. Deterministic PowerShell and Chocolatey capabilities](0018-deterministic-powershell-chocolatey-capabilities.md)

> Supersession note (2026-07-10): the unmodified installer could exit `0` without canonical Chocolatey. ADR 0022 is current and carries a narrow fork that serializes finalization, propagates failures, and supports verified offline inputs.

## Decision

Cage's `chocolatey` module will wrap PietJankbal Chocolatey-for-wine's upstream installer path instead of partially reconstructing that installer as separate Cage-owned PowerShell, .NET, nupkg, registry, and native-promotion steps.

The module still provides Cage-specific determinism around the upstream boundary:

1. Download the pinned Chocolatey-for-wine release archive.
2. Verify the release archive SHA-256.
3. Extract the archive into the module cache.
4. Locate `ChoCinstaller_*.exe` from the release.
5. Run the upstream installer with noninteractive flags:

   ```bash
   wine ChoCinstaller_*.exe /s /q
   ```

   `/s` preserves installer downloads/cache state and `/q` prevents the automatic PowerShell window launch.
6. Verify canonical `C:/ProgramData/chocolatey/bin/choco.exe`.
7. Write Cage metadata/logs around the upstream installer and Chocolatey verification.
8. Run requested packages through canonical Chocolatey only after diagnostics pass.

The recipe contract does not change:

```yaml
modules:
  - type: chocolatey
    install:
      packages:
        - firefox
        - 7zip.install
```

Under ADR 0019's now-superseded design, `chocolatey` and `powershell-wrapper` remained temporarily incompatible in one recipe because both owned overlapping PowerShell/profile/shim state. ADR 0020 returns the Chocolatey side to Cage-owned sequential capability slots for the MVP while preserving the future capability resolver as the v2 composition path.

## Reasoning

ADR 0018 was a reasonable response to the first failure class: upstream `ChoCinstaller_*.exe` hid internal failures and looked too interactive/non-deterministic for a container build module.

Further evidence changed the tradeoff:

- The manual reconstruction kept rediscovering hidden Chocolatey-for-wine compatibility state.
- Raw Chocolatey payload promotion could produce the right file layout while still failing to run `choco.exe`.
- The latest diagnostics showed Wine loading builtin `mscoree.dll` and failing with `Wine Mono is not installed`, despite manual .NET/registry work.
- This means the upstream project is not just a file layout; it is a compatibility environment. Cage was effectively reimplementing upstream one side effect at a time.

For current zero-user Cage, reliability and upstream fidelity beat a cleaner-looking but incomplete bootstrap. Cage should wrap the proven upstream path, pin/checksum it, bound it with timeouts, and collect better evidence when it fails.

## Consequences

- Chocolatey setup is less internally decomposed, but much closer to the upstream behavior users expect.
- Failures inside `ChoCinstaller_*.exe` are treated as an upstream boundary and diagnosed with Cage logs/metadata rather than reimplemented piecemeal.
- The module cache remains useful for the release archive and upstream download cache (`CFW_CACHE`).
- Existing deterministic PowerShell/nupkg/.NET/native-promotion tests and docs are deprecated.
- The PowerShell capability resolver remains future work for composing `chocolatey` with `powershell-wrapper`, but it no longer needs to make Chocolatey depend on a Cage-owned PowerShell finalizer.

## Rejected alternatives

- **Continue patching the manual reconstruction.** Rejected because each fix exposed another hidden upstream side effect.
- **Pre-bake Chocolatey immediately into a runtime image.** Deferred; the upstream wrapper should first prove the compatibility path and produce diagnostics.
- **Drop diagnostics and just run upstream.** Rejected. Cage still needs bounded timeouts, canonical `choco.exe` gating, and uploadable failure artifacts for CI/debug loops.

## Review triggers

Revisit when:

- A real build proves upstream `ChoCinstaller_*.exe /s /q` fails deterministically in Cage's Wine image.
- Upstream changes release layout or installer flags.
- A recipe needs both `chocolatey` and `powershell-wrapper` in one prefix.
- Bootstrap time becomes the dominant bottleneck and a pre-baked Chocolatey build image becomes clearly higher leverage.
