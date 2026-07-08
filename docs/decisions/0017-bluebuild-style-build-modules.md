# 0017. BlueBuild-style build modules

Status: accepted / implemented
Date: 2026-07-02
Owner: Cage technical direction

## Decision

Cage will model reusable build-time package-manager/tooling chains as top-level BlueBuild-style `modules[]` entries rather than primarily as raw `install[]` steps or profiles.

The first implemented module is Chocolatey:

```yaml
modules:
  - type: chocolatey
    install:
      packages:
        - firefox
        - 7zip.install
```

This deliberately mirrors the myOS/BlueBuild DNF pattern:

```yaml
modules:
  - type: dnf
    install:
      packages:
        - gcc
```

## Rationale

Chocolatey is not a single installer step under Wine. The reliable path is PietJankbal's Chocolatey-for-wine release, which owns its own PowerShell/CoreCLR setup, Wine compatibility shims, Chocolatey bootstrap, and package install surface.

Putting that chain behind `modules[].type: chocolatey` keeps recipes declarative and lets Cage own the setup/install logic. Cage also exposes Synchro's PowerShell wrapper as a separate `modules[].type: powershell-wrapper` capability, but `chocolatey` and `powershell-wrapper` are temporarily incompatible in the same recipe because both replace the same Wine PowerShell surface with different compatibility layers. Raw `install.kind: choco` remains only the lowered internal build-step representation.

## Consequences

- Recipe schema now includes `modules[]`.
- Modules execute in declaration order as first-class build directives.
- The initial built-in module registry is Python-backed under `core/modules/`.
- A future external registry can move definitions to `modules/<name>/module.yaml` without changing the user-facing YAML shape.
- Build containers need network access for Chocolatey; runtime containers remain air-gapped by default through `runtime.network: none`.

## Rejected alternatives

- **Profile-based Chocolatey**: profiles are static compatibility/dependency defaults and do not model parameterized package installation well.
- **User-authored `install.kind: choco` as the primary API**: this repeats setup concerns and is less like the myOS/BlueBuild module model.
- **Containerfile-only Chocolatey**: this hides Wine-prefix setup inside image layers and does not fit Cage's application artifact build model.

## Review triggers

Revisit this decision if Cage adds external module registries, module version pinning, offline package sources, or a pre-baked Chocolatey runtime/build image.
