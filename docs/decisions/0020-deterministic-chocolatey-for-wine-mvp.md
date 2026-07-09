# 0020. Deterministic Chocolatey-for-wine MVP reconstruction

Status: accepted
Date: 2026-07-09
Owner: Noah Giroux / CTO
Supersedes: [0019. Upstream Chocolatey-for-wine wrapper](0019-upstream-chocolatey-for-wine-wrapper.md)
Refines: [0018. Deterministic PowerShell and Chocolatey capabilities](0018-deterministic-powershell-chocolatey-capabilities.md)

## Decision

Cage's `chocolatey` module will not trust PietJankbal Chocolatey-for-wine's `ChoCinstaller_*.exe` as the build success boundary for the MVP.

Instead, Cage will consume Chocolatey-for-wine as pinned upstream evidence/data and execute the required setup as sequential, named, verifiable build steps:

1. install the pinned/checksummed PowerShell MSI class that upstream expects;
2. download/checksum/extract the pinned Chocolatey-for-wine release archive;
3. download/checksum `winetricks.ps1` from the matching upstream tag;
4. download/checksum/extract the pinned Chocolatey nupkg into raw `C:/ProgramData/tools/ChocolateyInstall`;
5. extract and flatten upstream `c_drive.7z` into the Wine `drive_c` instead of allowing a nested `drive_c/c:` tree;
6. install .NET Framework 4.8 through sequential x64 then x86 MSI steps, never in parallel with another MSI operation, so both 64-bit and WOW64 native CLR files exist. MSI return codes are advisory after this point: if Wine reports an MSI block such as `NEWERVERSIONDETECTED` / `INSTALL Return value 0`, Cage treats the step as successful only when the required native CLR markers already exist. The order matters: an x86-first install can make the x64 MSI report `NEWERVERSIONDETECTED` before 64-bit CLR markers are created;
7. apply the Wine/.NET registry state needed by upstream, including native `mscoree` for Chocolatey;
8. promote the raw Chocolatey payload into canonical `C:/ProgramData/chocolatey/bin/choco.exe` with native file operations, not through a PowerShell finalizer. Canonical `bin/choco.exe` must be the real root Chocolatey executable from the nupkg, not the upstream `redirects/choco.exe` shim; a real build showed the 147 KB redirect shim can become the failing `mscoree.dll not found` loader boundary;
9. run structured Chocolatey readiness diagnostics before package install;
10. apply upstream Chocolatey feature policy before installs:
    - `choco feature disable --name=powershellHost`
    - `choco feature enable -n allowGlobalConfirmation`
11. install requested packages only through canonical `C:/ProgramData/chocolatey/bin/choco.exe`.

The recipe contract remains:

```yaml
modules:
  - type: chocolatey
    install:
      packages:
        - firefox
        - 7zip.install
```

`chocolatey` and `powershell-wrapper` remain temporarily incompatible in one recipe because both own overlapping PowerShell/profile/shim state. The future capability resolver remains useful, but the MVP path prioritizes a working, diagnosable Chocolatey module over a cleaner v2 composition model.

## Evidence

ADR 0019 intentionally named this review trigger: revisit if a real build proves upstream `ChoCinstaller_*.exe /s /q` fails deterministically in Cage's Wine image.

That trigger fired. A real Notepad++ Chocolatey build produced:

```json
{
  "installerExitCode": 0,
  "chocoExists": false,
  "chocoVersionExitCode": 127
}
```

The corresponding upstream installer log contained only archive extraction output (`c_drive.7z`, .NET payload extraction, Chocolatey nupkg extraction) and no reported error. Upstream source explains the shape: `ChoCinstaller` starts multiple setup threads, ignores child-process success boundaries, and relies on a later PowerShell `choc_install.ps1` finalizer to move raw `ProgramData/tools/ChocolateyInstall` into canonical `ProgramData/chocolatey`. In the Cage container, the upstream executable can exit `0` before producing canonical Chocolatey.

Therefore pure upstream wrapping regressed the MVP: it hid the failure earlier than the deterministic reconstruction.

## Reasoning

The right distinction is not "upstream versus custom." The right distinction is the success boundary.

For MVP:

- Upstream remains the behavioral reference: pinned versions, payload layout, c_drive contents, .NET/PowerShell prerequisite class, registry policy, native `mscoree`, Chocolatey feature settings.
- Cage owns the execution boundary: sequential steps, checksums, bounded timeouts, concrete file/registry markers, diagnostic JSON/logs, and canonical `choco.exe` gating.
- The opaque `ChoCinstaller` executable is useful evidence, but not a reliable success boundary inside fresh deterministic container builds.

This path is less elegant than a future v2 module, but it is more likely to produce a working MVP and better failure evidence.

## Consequences

- ADR 0019 is superseded.
- The module again has multiple explicit setup steps rather than one upstream-wrapper step.
- Diagnostics can identify whether failure happened in PowerShell MSI, data extraction, .NET x64/x86 MSI install, registry prep, native promotion, Chocolatey verification, feature policy, or package install.
- The module may still be refined toward a v2 capability/provider model later.
- Pre-baking Chocolatey into a build image remains parked until this module path works and bootstrap time becomes the bottleneck.

## Rejected alternatives

- **Keep pure `ChoCinstaller_*.exe /s /q` wrapper.** Rejected by uploaded real-build evidence: exit `0`, canonical `choco.exe` absent.
- **Treat raw `tools/ChocolateyInstall` as success.** Rejected because package install and provenance must use canonical Chocolatey.
- **Return to partial manual reconstruction without upstream behavior.** Rejected. The reconstruction must remain upstream-derived: pinned CFW data, c_drive flattening, .NET/PowerShell prerequisite class, native CLR policy, and Chocolatey feature policy.
- **Pre-bake Chocolatey immediately into a runtime/build image.** Deferred. It may be valuable after the module path works, but it should not hide the current bootstrap failure boundary.

## Review triggers

Revisit when:

- A real Notepad++ or VS Code Chocolatey recipe passes package install end-to-end.
- Diagnostics show the sequential path still fails at a stable boundary.
- A recipe needs both `chocolatey` and `powershell-wrapper` in one prefix.
- Bootstrap time dominates and a pre-baked `cage-wine-choco` build image becomes higher leverage.
