# 0018. Deterministic PowerShell and Chocolatey capabilities

Status: accepted
Date: 2026-07-08
Owner: Noah Giroux / CTO

## Decision

Cage will stop executing PietJankbal Chocolatey-for-wine's `ChoCinstaller_*.exe` in the `chocolatey` module.

Cage will continue to consume the pinned Chocolatey-for-wine release as upstream data — especially `choc_install.ps1` and compatibility payloads — but Cage owns the deterministic bootstrap sequence itself.

The `chocolatey` module will be rebuilt as sequential, individually verifiable build steps:

1. Install a real PowerShell 7 engine from a pinned, host-downloaded, SHA-256 verified ZIP payload. No PowerShell MSI path is used.
2. Download the Chocolatey nupkg with host networking, verify SHA-256, and extract the nupkg as a ZIP into the Wine prefix.
3. Install .NET 4.8 in its own build step by host-downloading the pinned installer, extracting `netfx_Full_x64.msi`, and running one dedicated `msiexec /QN` with a generous timeout. This step must never run in parallel with another MSI operation.
4. Prepare Wine registry/runtime state: set the prefix Windows version to `win10` and apply the `pwsh.exe` DLL overrides required by Chocolatey-for-wine.
5. Prove PowerShell execution before finalization. A `pwsh.exe` file and Wine exit code `0` are not sufficient; Cage must verify output, sentinel creation, and expected exit-code propagation through both `-Command` and script-file invocation.
6. Finalize through a verified Chocolatey-for-wine compatibility boundary. Prefer the pinned Chocolatey-for-wine `WindowsPowerShell/v1.0/powershell.exe` wrapper/profile path; if that boundary cannot be made deterministic, port the required finalizer contract natively instead of adding more raw `pwsh.exe -File` path patches.
7. Verify only canonical `C:/ProgramData/chocolatey/bin/choco.exe`; the raw `tools/chocolateyInstall` payload is a recovery marker, never success.

Cage will introduce a PowerShell capability contract as the composability foundation for future `chocolatey` + `powershell-wrapper` coexistence. The contract has three slots:

- **engine** — a real `pwsh` 7 runtime; exactly one provider per prefix.
- **winps-shim** — owner of `system32/syswow64/WindowsPowerShell/v1.0/powershell.exe`.
- **shim-library** — versioned/layered `profile.ps1`-style shim assets, not uncoordinated file overwrites.

Modules will declare `requires`/`provides` against these slots. The builder will resolve providers, order steps, hard-error on conflicts during manifest validation, and record resolved providers in `graph.json`/provenance like runtime images.

Long-term module hygiene: multi-hundred-line shell heredocs inside Python f-strings are deprecated. Non-trivial module scripts should move to packaged script templates or small composable build steps.

## Verified findings

External review and failed build artifacts confirmed that `ChoCinstaller_*.exe` is incompatible with Cage's deterministic build model:

- It exits `0` regardless of internal failures.
- It starts four unsynchronized threads: `c_drive.7z` extraction, .NET 4.8 MSI, PowerShell MSI via Wine URLMon/WinINet, and Chocolatey nupkg extraction.
- It parses the PowerShell version from fixed filename character offsets.
- It downloads/caches through Wine desktop-prefix assumptions such as `MyDocuments/CFW_CACHE`.
- It was designed for interactive desktop prefixes where caches persist and the runner is full desktop-style, not fresh deterministic container builds.
- It still encoded useful side effects Cage must replace explicitly: PowerShell registry/environment setup, prerequisite/cache staging, the `WindowsPowerShell/v1.0/powershell.exe` wrapper boundary, profile-loading behavior, and QPR/system-command shims.
- Current failure artifacts showed standalone ZIP `pwsh.exe -File` could return success while producing no sentinel, no stdout, and no canonical Chocolatey output. That makes PowerShell execution proof a hard prerequisite, not a diagnostic warning.

Observed Cage failure mode: raw Chocolatey nupkg extraction can win while the PowerShell MSI silently fails due to parallel MSI work in a fresh Wine prefix. That leaves raw `ProgramData/tools/chocolateyInstall/choco.exe` but no reliable `pwsh.exe`, and Cage correctly refuses to treat that state as success.

## Sequencing

### Phase 1 — now

- Rebuild `chocolatey` around deterministic D2 steps above.
- Extract the PowerShell engine step into a shared module/component consumed by both `chocolatey` and `powershell-wrapper`.
- Keep and enforce temporary `chocolatey`/`powershell-wrapper` mutual exclusion in manifest validation until capabilities land.
- Add SHA-256 verification to `powershell-wrapper` Codeberg release downloads.
- Add `--module-cache-dir` parallel to `--runner-cache-dir` so module payloads survive across builds.

### Phase 2 — next

Implement the PowerShell capability `requires`/`provides` resolver and record resolved providers in graph/provenance.

### Phase 3 — not now

Profile/shim layering for coexistence is parked until the first recipe needs both Chocolatey packages and WinPS-dependent installers.

Reactivation condition: a real recipe requires both `chocolatey` packages and WindowsPowerShell-dependent installer behavior in the same prefix.

When reactivated, vendor a pinned/checksummed `profile.ps1` as a Cage asset with an upstream-sync policy and dot-source chain so Chocolatey-for-wine shim functions and Synchro wrapper functions can coexist.

## Consequences

- Builds become slower per first prefix because Cage explicitly performs each setup step, but failures become attributable to named phases.
- Build logs and failure analysis will identify whether PowerShell engine install, nupkg extraction, .NET install, registry prep, finalization, or package installation failed.
- Cage no longer depends on Chocolatey-for-wine's non-deterministic, interactive bootstrapper behavior.
- The old `ChoCinstaller`/`pwsh` verification loop is deprecated; preserve it only as historical debugging evidence.
- The current mutual exclusion is deliberate, temporary architecture debt with a clear resolver path.

## Rejected alternatives

- **Keep patching `ChoCinstaller_*.exe` execution.** Rejected because the bootstrapper's thread model and success semantics are incompatible with Cage's deterministic model.
- **Treat raw `tools/chocolateyInstall` as success.** Rejected because package install and provenance must use canonical Chocolatey.
- **Merge Synchro's wrapper into `chocolatey` ad hoc.** Rejected because it would replace one hidden compatibility collision with another. Capabilities must make ownership explicit first.
- **Pre-bake all Chocolatey state into a runtime image immediately.** Deferred; deterministic module steps remain useful for provenance and for proving the capability contract.

## Review triggers

Revisit this decision when:

- The PowerShell capability resolver lands.
- A recipe needs both Chocolatey and WindowsPowerShell-dependent installers.
- Cage adds external module registries or packaged module script templates.
- Chocolatey, PowerShell, .NET, or wrapper upstream versions change.
- Phase 1 exceeds roughly one week of effort and threatens the Nereus MVP focus tradeoff.
