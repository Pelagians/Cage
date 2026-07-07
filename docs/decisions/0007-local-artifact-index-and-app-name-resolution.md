# Decision 0007: Local Artifact Index and App-Name Resolution

Date: 2026-06-28

Status: accepted

## Decision

Cage maintains a local artifact index at `dist/.cage/artifacts.json` by default. `cage build` registers each successfully materialized bundle in that index, keyed by application name and version.

The index schema is `cage.artifact-index/v0`. It records the bundle path, graph path, application identity, resolved runner runtime, launch contract, provenance summary, verification status, and a `latest` pointer per application.

The CLI accepts either direct bundle paths or app references for downstream commands:

```text
cage run notepad-plus-plus
cage run notepad-plus-plus@8.6.0
cage export oci notepad-plus-plus --tag local/notepad:8.6.0
```

Direct bundle paths remain supported for debugging and automation. App references resolve through the local artifact index. `name` resolves to the latest registered version for that app; `name@version` resolves to the pinned version.

## Reasoning

This moves the user experience toward the application-first model without removing the lower-level bundle directory. Users should not have to remember `dist/<name>-<version>` paths for ordinary run/export flows. The bundle remains the current internal/debug/staging representation, while the artifact index provides a stable app-name lookup layer.

The index is local and filesystem-backed for v0. It is not a registry, trust database, lockfile, or production source of truth. Future registry-backed artifact stores can reuse the app-name reference model once OCI push/digest recording and post-pull metadata verification are in place.

## Contract

- Default index path: `dist/.cage/artifacts.json`.
- Schema: `cage.artifact-index/v0`.
- Build registration requires a valid bundle according to `cage bundle verify`.
- `name` resolves through the index `latest` pointer.
- `name@version` resolves to a specific registered version.
- `cage run` and `cage export oci` accept either a bundle path or an indexed app reference.
- `cage artifacts list` prints the local index.
- `cage artifacts resolve <ref>` prints the resolved entry.

## Rejected alternatives

- Make users pass bundle directory paths forever.
- Treat the bundle directory name as the only app identity.
- Add Kubernetes manifest generation before app artifact identity and local resolution are stable.
- Make this v0 index a remote registry or production trust root.

## Review triggers

Review this decision when Cage records pushed OCI digests, adds an artifact registry, verifies label/metadata consistency after pull, or supports multiple output/index roots in a single workspace.
