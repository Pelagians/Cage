# 0022. Deterministic Chocolatey-for-Wine fork

Status: accepted
Date: 2026-07-10
Owner: Noah Giroux / CTO
Supersedes: [0021. Upstream-first Chocolatey-for-Wine bootstrap](0021-upstream-first-chocolatey-bootstrap.md)

## Decision

Cage will consume the pinned `noahgiroux/Chocolatey-for-wine` prerelease `v0.5c.755-noah.3`, derived from `Twig6943/Chocolatey-for-wine` and ultimately `PietJankbal/Chocolatey-for-wine`.

The fork keeps upstream compatibility behavior and release layout but patches installer orchestration:

1. .NET, Chocolatey payload, and `c_drive` prerequisites may run concurrently;
2. PowerShell installation and `choc_install.ps1` finalization start only after all prerequisite workers succeed;
3. process, thread, download, and PowerShell failures propagate to the installer exit code;
4. PowerShell uses terminating error behavior;
5. installer success requires canonical `C:/ProgramData/chocolatey/bin/choco.exe`.

Cage still treats the installer as a bootstrap mechanism, not proof of readiness. It independently requires canonical Chocolatey, bounded command probes, feature policy, and a local install/uninstall lifecycle before user packages run.

## Provenance

- Fork commit: `6b8f27fa49c8edf4db8edc972d13e3e3f9839b2b`
- Release: `v0.5c.755-noah.3`
- Asset SHA-256: `2dc2f5f48e0328875d566757ba1c4e6fbd92d1bb6d8372418dc666c27ebc54a5`
- Installer build/package CI: passed before Cage integration
- Canonical upstream: `PietJankbal/Chocolatey-for-wine`, monitored weekly and manually by the fork without automatic merging

## Reasoning

The unmodified upstream installer reproduced the failure previously recorded in ADR 0019: it could return success before concurrent extraction/finalization produced canonical Chocolatey. The manual reconstruction in ADR 0020 reached a different failure at managed CLR startup. A narrow fork fixes the proven upstream orchestration defect while avoiding another compatibility reimplementation.

## Consequences

- The active profile is `cfw-v0.5c.755-noah.3-choco-2.6.0-fork-r9`.
- Cage stores the complete installer output as lifecycle evidence but emits only the fork's fixed `[cfw] stage=...` progress records to live CI logs.
- The release tag and packaged installer version are represented separately because the asset contains `ChoCinstaller_0.5c.755.exe`.
- Cage depends on a personally owned fork while this remains an upstream contribution experiment. Transfer it to Pelagians before treating it as a permanent supported production dependency if upstream does not merge the fixes.
- Reconsider when upstream merges equivalent sequencing/error handling, canonical upstream changes materially, or Cage lifecycle CI disproves the fork.
