# Historical migration fixtures

The two runtime files are unmodified Cage sources from commit
`10c295a` (the qualified desktop release before generation management).
They retain the repository's MIT license. They are test inputs only, never
selected by production build/export commands.

`scripts/prepare-legacy-poc.py` packages these historical helpers around the
same verified application seed and runtime as a managed baseline. This proves
migration from an actual old launcher and old AppImage installation receipt,
rather than merely editing a modern prefix's state marker.
