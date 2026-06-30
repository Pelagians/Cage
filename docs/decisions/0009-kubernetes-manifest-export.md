# Decision 0009: Kubernetes Manifest Export

Date: 2026-06-28

Status: accepted

## Decision

WinForge emits Kubernetes manifests for verified WinForge application images, but does not apply them to a cluster.

`winforge export kube <bundle-or-app-ref> --image <image@sha256:...>` consumes a verified bundle, either directly or through the local artifact index, and emits `winforge.kube-export/v0` plus Kubernetes YAML for running the already-built application image.

Digest-pinned image refs are required by default. Mutable tag refs are rejected unless `--allow-mutable-tag` is explicitly supplied.

## Generated resources

The v0 emitter writes:

- `PersistentVolumeClaim` for runtime state unless `--no-pvc` is set;
- `PersistentVolumeClaim` for exports unless `--no-pvc` is set;
- `Deployment` for the WinForge application image.

The Deployment mounts:

```text
/var/lib/winforge/state
/exports
```

and sets:

```text
WINFORGE_STATE=/var/lib/winforge/state
WINFORGE_EXPORTS=/exports
WINFORGE_GRAPHICS=headless
```

`--no-pvc` uses `emptyDir` volumes for smoke/demo manifests. Kubernetes labels are normalized for selector/tooling safety. Exact WinForge metadata such as schema, raw app name, app version, and image ref is preserved in annotations.

## Boundary

This is a manifest emitter, not an operator. WinForge must not create namespaces, apply resources, manage tenants, own approvals, or become VIC's production automation authority. VIC or a human/operator may consume the generated YAML later.

## Reasoning

Earlier phases made artifact identity stable enough for Kubernetes: bundles can become runnable OCI images, pushed images can record repo digests, and image metadata can be verified. Kubernetes manifests should therefore reference digest-pinned images and preserve the artifact/runtime-state/export boundary.

## Rejected alternatives

- Generate manifests from mutable image tags by default.
- Run `kubectl apply` from WinForge.
- Add VIC tenancy/session/policy concepts to WinForge manifests.
- Require a live cluster for manifest generation.

## Review triggers

Review when WinForge adds manifest validation, Helm/Kustomize output, Services/Ingress for visible sessions, multi-container sidecars, or VIC-specific orchestration integrations.
