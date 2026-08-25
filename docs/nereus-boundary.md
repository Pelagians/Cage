# Nereus / Cage Boundary

Cage and Nereus must stay separate.

## 1. What part of Nereus interacts with Cage?

Only the Nereus artifact-consumption/runtime orchestration side should interact with Cage outputs: registry integration, runtime job launcher, compatibility-pack catalog, or worker path that references a Cage bundle/OCI image.

## 2. What artifacts does Nereus consume?

Sealed execution bundles or OCI images, normalized manifest metadata, runtime binding metadata, launch definitions, provenance, and build logs.

## 3. Where does Nereus begin and Cage end?

Cage ends when an artifact is sealed. Nereus begins when that sealed artifact is selected, scheduled, governed, audited, and exposed through product workflows.

## 4. Why Nereus must not contain Cage logic

Reproducibility, open-source boundary, consumer neutrality, auditability, security, and maintainability all require the artifact to be buildable outside Nereus.

## 5. What integration boundary exists?

Preferred boundaries: OCI image, bundle archive/directory, CLI contract, and possibly a future artifact build API. Nereus should never depend on private modules inside Cage.
