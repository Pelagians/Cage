# Decision 0008: OCI Digest Recording and Image Verification

Date: 2026-06-28

Status: accepted

## Decision

WinForge records pushed OCI image identity and verifies application image metadata after build/pull.

`winforge export oci <bundle-or-app> --tag <image> --push` builds and pushes the runnable application image, then inspects the local image record to capture `RepoDigests` and the concrete digest when available.

`winforge image verify <image>` verifies that OCI labels match the embedded WinForge artifact metadata at `/opt/winforge/bundle/metadata/artifact.json`.

## Contract

Digest recording uses `docker image inspect` or `podman image inspect` after a successful push. The export result includes:

```text
schemaVersion: winforge.oci-export-result/v0
push.digest: sha256:...
image.schemaVersion: winforge.oci-image-inspection/v0
image.repoDigests: [...@sha256:...]
image.labels: {...}
```

Image verification uses `schemaVersion: winforge.oci-image-verification/v0` and checks at least:

- `io.winforge.schema` equals embedded `schemaVersion`;
- app name/version labels equal embedded `application` metadata;
- runtime provider/requestedVersion/resolvedVersion/baseImage labels equal embedded runtime metadata;
- runner and launcher labels equal embedded runtime metadata.

Verification fails closed: if the engine is missing, image inspect fails, embedded metadata cannot be read, metadata JSON is invalid, or labels disagree with metadata, the result is `valid: false`.

## Reasoning

Kubernetes and customer deployment should eventually refer to immutable image digests, not mutable tags. Labels are useful for schedulers, registries, and quick inspection, but embedded WinForge metadata is the artifact semantic record. Verification keeps those two views from silently diverging.

This also protects the application-first model: the OCI image is a deployable artifact identity, while WinForge metadata describes the app, runtime, launch contract, state, and exports.

## Rejected alternatives

- Treat pushed tags as sufficient deployment identity.
- Trust OCI labels without checking embedded metadata.
- Require Kubernetes manifest generation before image identity and metadata verification exist.

## Review triggers

Review when WinForge adds remote registry discovery, signs attestations/SBOMs, supports multi-arch images, verifies by digest after pull, or emits Kubernetes manifests that pin application images by digest.
