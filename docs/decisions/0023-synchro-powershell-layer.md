# ADR 0023: Synchro owns the Windows PowerShell compatibility layer

- Status: Accepted
- Date: 2026-07-10

## Context

Cage previously treated the Chocolatey-for-Wine installer as a self-contained
provider of the PowerShell engine, Windows PowerShell shims, profile behavior,
.NET compatibility, and Chocolatey. That made ownership ambiguous and left two
unrelated PowerShell implementations in the same prefix.

The selected layer-two implementation is Synchro's
`powershell-wrapper-for-wine` v4.2.0. Cage also needs CFW's Wine-specific
Chocolatey knowledge without allowing CFW to replace the engine, wrappers, or
root profile.

## Decision

Cage composes the stack in this order:

1. The current CFW bootstrap temporarily establishes its .NET prerequisites and
   canonical Chocolatey layout.
2. Cage replaces any PowerShell result with the pinned PowerShell 7.4.11 ZIP
   engine and proves the exact version through direct execution.
3. Cage installs the pinned Synchro v4.2.0 x64 and x86 wrapper executables.
4. Cage owns `C:\Program Files\PowerShell\7\profile.ps1` as a stable loader.
5. Synchro's unmodified profile is stored under
   `C:\ProgramData\Cage\PowerShell\upstream` and loaded by
   `profile.d\10-synchro.ps1`.
6. CFW contributes ordered, additive fragments beginning at slot 20.
7. Chocolatey lifecycle tests run only after the complete PowerShell layer has
   passed x64, x86, profile-loading, and exit-code propagation probes.

The exclusive capability providers are:

- `engine`: `powershell-zip-7.4.11`
- `winps-shim`: `synchro-v4.2.0`
- `package-manager`: `chocolatey-2.6.0`
- `compatibility-pack`: `chocolatey-for-wine-v1`

The CFW compatibility fragments are vendored from commit
`c3b4923d0f63188843bd2a15be64bca8f4a9902b` of Noah Giroux's fork.

## Transitional limitation

The released CFW bootstrap still installs a PowerShell MSI internally. Cage
immediately replaces that directory and does not advertise the MSI as its
engine. This is transitional, not the desired final architecture.

The next CFW release should expose a prerequisite-only or layer-three bootstrap
that never installs PowerShell. Once that release exists, Cage will remove the
transitional MSI download and installer behavior from its bootstrap profile.

## Consequences

- Chocolatey and the standalone PowerShell wrapper module now resolve to the
  same engine and shim providers and may be used together.
- Arbitrary unverified Synchro versions are rejected.
- The root PowerShell profile is no longer copied directly from an upstream
  project.
- CFW profile behavior is additive, ordered, hashable, and independently
  testable.
- A zero exit code alone is insufficient. Every PowerShell boundary requires an
  expected marker, side effect, and exit-code assertion.
