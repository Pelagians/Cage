# 0022. Deterministic Chocolatey-for-Wine fork

Status: accepted
Date: 2026-07-10
Owner: Noah Giroux / CTO
Supersedes: [0021. Upstream-first Chocolatey-for-Wine bootstrap](0021-upstream-first-chocolatey-bootstrap.md)

## Decision

Cage will consume the pinned `noahgiroux/Chocolatey-for-wine` prerelease `v0.5c.755-noah.6`, derived from `Twig6943/Chocolatey-for-wine` and ultimately `PietJankbal/Chocolatey-for-wine`.

The fork keeps upstream compatibility behavior and release layout but patches installer orchestration:

1. .NET, Chocolatey payload, and `c_drive` prerequisites may run concurrently;
2. finalization starts only after all prerequisite workers succeed;
3. process, thread, download, and finalizer failures propagate to the installer exit code;
4. desktop mode retains the upstream-derived PowerShell finalizer with terminating error behavior and explicit `argv[0]`/`-File` invocation;
5. verified-offline container mode (`CFW_CONTAINER_BUILDER=1` plus `CFW_OFFLINE=1`) replaces only the proven no-op PowerShell script boundary with a native finalizer;
6. native finalization rejects stale/reparse-point state, promotes the real root `choco.exe` through an exclusive temporary file and atomic rename, and persists `ChocolateyInstall` plus canonical `bin` on `Path`;
7. fixed stage records distinguish prerequisite, desktop, native-finalizer, canonical-check, and completion boundaries;
8. installer success requires canonical `C:/ProgramData/chocolatey/bin/choco.exe`.

Cage still treats the installer as a bootstrap mechanism, not proof of readiness. It independently requires canonical Chocolatey, bounded command probes, feature policy, and a local install/uninstall lifecycle before user packages run.

## Provenance

- Fork commit: `9d635ecdba9b10103c202fea51dbaba70aec4d83`
- Release: `v0.5c.755-noah.6`
- Asset SHA-256: `25c2e3cd544c7f83e9c196a5b8b0f98e020b4f5e24f19de30ea6ceec585d0792`
- Installer build/package CI: passed before Cage integration
- Canonical upstream: `PietJankbal/Chocolatey-for-wine`, monitored weekly and manually by the fork without automatic merging

## Reasoning

The unmodified upstream installer reproduced the failure previously recorded in ADR 0019: it could return success before concurrent extraction/finalization produced canonical Chocolatey. The first fork releases corrected sequencing and error propagation, but Cage then proved that MSI-installed `pwsh.exe` returns `0` without executing output or filesystem effects in the Wine 11 container across direct and script-file boundaries. The manual reconstruction in ADR 0020 reached a different failure at managed CLR startup. The accepted split preserves upstream desktop behavior while making verified-offline container promotion a narrow native fork responsibility; Cage still owns payload digest verification and end-to-end readiness/lifecycle proof.

## Consequences

- The active profile is `cfw-v0.5c.755-noah.6-choco-2.6.0-fork-r12`.
- Cage stores the complete installer output as lifecycle evidence but emits only the fork's fixed `[cfw] stage=...` progress records to live CI logs.
- The release tag and packaged installer version are represented separately because the asset contains `ChoCinstaller_0.5c.755.exe`.
- Cage depends on a personally owned fork while this remains an upstream contribution experiment. Transfer it to Pelagians before treating it as a permanent supported production dependency if upstream does not merge the fixes.
- Reconsider when upstream merges equivalent sequencing/error handling, canonical upstream changes materially, or Cage lifecycle CI disproves the fork.
