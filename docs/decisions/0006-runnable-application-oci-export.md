# Decision 0006: Runnable Application OCI Export

Date: 2026-06-28

Status: accepted

## Decision

Cage exports application bundles as **runnable application OCI images**. The image is based on the graph-resolved runtime image and embeds the verified bundle at `/opt/cage/bundle`.

The exported image includes an application launcher at `/usr/local/bin/cage-app-launch`, embedded Cage artifact metadata at `/opt/cage/bundle/metadata/artifact.json`, OCI labels that mirror core metadata, and explicit mutable paths for runtime state and exports:

```text
/opt/cage/bundle      immutable embedded bundle
/var/lib/cage/state   mutable runtime state / copied prefix
/exports                  explicit app/user output surface
/usr/local/bin/cage-app-launch
```

`cage export oci <bundle> --tag <image> --dry-run` emits `cage.oci-export-plan/v0` without building. `cage export oci <bundle> --tag <image>` stages a build context and runs `podman build` or `docker build`.

## Contract

The OCI export contract consumes a verified bundle. Export fails before planning/building if `cage bundle verify <bundle>` would fail.

The plan and embedded artifact metadata record both the originally requested runtime version and the resolved pinned runtime version. Mutable aliases such as `latest` are never artifact identity.

The exported application image is runnable because it contains:

- the resolved runtime base image via `FROM <runnerRuntime.image>`;
- the sealed bundle copied under `/opt/cage/bundle`;
- `metadata/artifact.json` with `schemaVersion: cage.artifact-image/v0`;
- `cage-app-launch`, which prepares mutable runtime state and launches through `wine` or `umu-run` according to graph runtime metadata.

## Reasoning

A runnable app image keeps the UX application-first and lets a single image tag/digest identify the deployable application artifact. OCI storage still deduplicates the runtime base layers, while Cage metadata records the runtime provider, runner, launcher, and resolved version used to build the artifact.

Keeping runtime state outside `/opt/cage/bundle` preserves the sealed artifact. Runtime mutation, saves, caches, first-launch changes, and user exports belong in `/var/lib/cage/state` or `/exports`, not in the embedded bundle.

## Rejected alternatives

- Export artifact-only data images that require a separate runtime image plus init-copy glue at launch time.
- Treat `latest` as the artifact identity instead of resolving it to a pinned runner version.
- Mutate the source bundle directory by writing export-specific metadata into it. Export stages a build context and writes `artifact.json` into the staged copy instead.

## Review triggers

Review if Cage starts publishing digests, adds registry-backed artifact indexes, verifies OCI label/metadata consistency after pull, or changes runtime-state snapshot/export semantics.
