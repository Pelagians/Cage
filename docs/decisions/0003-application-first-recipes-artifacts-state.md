# Decision 0003: Application-First Recipes, Artifacts, and Runtime State

Date: 2026-06-28

Status: accepted

## Decision

Cage is application-first. Users should think "I am packaging an application" rather than "I am constructing a Wine prefix." Wine, Wine Staging, Proton-GE, prefixes, launch scripts, OCI layers, and container details are provider/runtime implementation details behind an application recipe and artifact lifecycle.

The primary shareable authoring format is strict YAML application recipes using `schemaVersion: cage.app/v0`. JSON remains supported as a normalized/generated format and for CLI-driven workflows; YAML is not the only possible build input, but it is the format different users and businesses should be able to write, store, review, and share.

The canonical deployable artifact direction is an OCI image digest containing the built application artifact, normalized recipe, metadata, provenance, launch contract, and runtime compatibility data. The current bundle directory remains an internal/debug/staging representation used by tests, inspection, verification, and local development.

Runtime state is separate from the immutable application artifact. The artifact contains what the recipe defines. Runtime execution may create or mutate application state, export files, save games, generate reports, install user-managed additions, or perform first-run setup, but those changes must not mutate the sealed artifact. Runtime state should be persisted separately by default and made explicit when exported or rebuilt into a new artifact.

## Practical rules

1. **Recipe-first UX**: the long-term happy path is `cage build app.yaml` and `cage run app`, with lower-level bundle commands retained for debugging and automation.
2. **Strict YAML**: YAML accepts only a schema-defined subset. Unknown fields, duplicate keys, anchors, aliases, and merge keys are rejected.
3. **JSON remains valid**: JSON is supported for normalized manifests, generated CLI input, tests, and automation.
4. **Build-time install**: Cage-managed install/dependency/config/registry steps happen at build time.
5. **Runtime mutation**: application-driven runtime mutation is allowed, persisted separately, and not considered reproducible artifact content.
6. **Runtime selection**: provider/version are selected at build time and enforced at run time. Rebuild when changing providers; future compatibility policies may allow carefully declared version movement.
7. **OCI identity, metadata semantics**: OCI digest identifies the deployable artifact; embedded Cage metadata describes it. OCI labels should match metadata or verification should fail.
8. **Graph scope**: the execution graph is build/provenance/contract metadata, not a general runtime scheduler.

## Reasoning

This keeps the Ramalama-like experience: users select or write a recipe, Cage resolves provider/runtime details, builds an application artifact, and then runs it with minimal user-facing complexity. Wine is only one runtime family behind the application lifecycle.

Wine/Proton prefixes are not byte-reproducible in practice because registry entries, caches, timestamps, GUIDs, fonts, shader caches, and app state mutate. Cage should instead target functional equivalence and auditable rebuildability given the same recipe, source artifacts, Cage version, and runtime provider image.

## Rejected alternatives

- Make users reason directly about Wine prefixes as the primary product concept.
- Treat the intermediate bundle directory as the canonical user-facing artifact forever.
- Require YAML as the only possible build input and block CLI/generated workflows.
- Allow arbitrary YAML features that make recipes ambiguous or hard to normalize.
- Let runtime execution modify the sealed build artifact.
- Make the graph a runtime scheduler.

## Review triggers

Review if Cage adds a registry-backed application catalog, a real artifact store, OCI export as the default build output, mutable runtime snapshot/export flows, or non-Wine runtime families.
