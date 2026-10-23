# Trusted releases and installation

Cage's trusted release client verifies publisher signatures and exact package
bytes **before** deployment. It delegates updates and rollback to the existing
Flatpak package transactions and shared Wine generation manager. It does not
introduce a second prefix format, compatibility implementation or hosted service.
The existing local export, migration, hosted, CFW and external-runner commands
keep their behavior.

## Install and use a release

Install Cage with its optional, standard Ed25519 implementation:

```sh
python -m pip install '.[releases]'  # From the Cage source checkout.
```

Obtain the publisher's public PEM key through an independently trusted channel.
Compare its fingerprint with the publisher's announcement; fetching a key beside
an untrusted download does not establish publisher identity. `release fetch`
prints the SHA-256 fingerprint of the raw Ed25519 public key after verification.
No key is discovered or accepted automatically.

```sh
cage release fetch https://publisher.example/releases/3.6/release.json \
  --key publisher-public.pem --format flatpak
cage release install https://publisher.example/releases/3.6/release.json \
  --key publisher-public.pem --format flatpak
cage release run io.github.Pelagians.Cage.SumatraPDF \
  --key publisher-public.pem --format flatpak -- "$HOME/Documents/Cage/example.pdf"

cage release update https://publisher.example/releases/3.6.1/release.json \
  --key publisher-public.pem --format flatpak -- "$HOME/Documents/Cage/example.pdf"
# Close the trial application normally to commit its new generation.
cage release rollback io.github.Pelagians.Cage.SumatraPDF \
  --key publisher-public.pem --format flatpak -- "$HOME/Documents/Cage/example.pdf"
cage release info io.github.Pelagians.Cage.SumatraPDF \
  --key publisher-public.pem --format flatpak
```

Use `--format appimage` for the same workflow. AppImage installation creates the
existing stable desktop menu entry; updates retain versioned packages and its
launcher dispatches to the package matching the committed prefix. Flatpak uses
its existing menu/file integration. Neither format changes default file handlers.
AppImage has ordinary host-user filesystem/network access; a signature does not
sandbox an application. Flatpak dependencies use the user's configured Flatpak
remotes and their trust policy. Cage does not add a remote or silently downgrade
a shared platform. Release metadata records the build runtime and qualification;
it does not freeze the host OS, graphics drivers or independently updated Flatpak
platforms.

Installation does not launch unless document arguments are supplied. A baseline
must have initialized its managed state before updating. An already-installed exact signed
baseline can be enrolled; a different existing package is refused. For older
packages, first use [supported legacy migration](application-onboarding.md) with
the existing local commands. Trusted delivery does not guess how to import an
arbitrary installation or untracked prefix.

## Containers

`oci` releases contain a hash-bound OCI image archive. Cage loads it through
Podman, checks its immutable image ID, architecture, embedded managed plan and
recipe digest, and never uses a mutable tag for application execution. Metadata
inspection uses `create`/`cp`/`rm`, without running code from the image.

```sh
cage release install ./release.json --key publisher-public.pem --format oci \
  --state-dir "$HOME/.local/share/my-sumatra-state" \
  --exports-dir "$HOME/Documents/SumatraPDF"
cage release run io.github.Pelagians.Cage.SumatraPDF \
  --key publisher-public.pem --format oci -- "$HOME/Documents/SumatraPDF/example.pdf"
cage release update ./next-release.json --key publisher-public.pem --format oci \
  -- "$HOME/Documents/SumatraPDF/example.pdf"
cage release rollback io.github.Pelagians.Cage.SumatraPDF \
  --key publisher-public.pem --format oci -- "$HOME/Documents/SumatraPDF/example.pdf"
```

Omitted directories default to private state/documents beneath the installation
ledger. Directory choices are fixed at installation and must be separate,
disjoint paths that do not expose the release cache. Documents passed to the
container must be within its explicit exports directory. Launches reuse the
qualified caller-UID desktop adapter, offline networking, explicit X11/Xauthority
mounts and persistent Wine state. Sharing an X11 display remains a desktop trust
grant. This client currently requires rootless Podman for its keep-id semantics;
existing Docker, hosted, headless, CFW and Proton workflows remain available
through their existing commands. Native container bundles are distributed through
their existing OCI export, rather than a new archive/prefix layout.

## Recovery, persistence and storage

The private default cache is `$XDG_DATA_HOME/cage/releases` (normally
`~/.local/share/cage/releases`). `--cache-dir` selects a different retained root;
use the same root for subsequent commands. It contains:

- `releases/<manifest-sha256>/`: original signed metadata, detached signature,
  exact package/archive, export receipt where applicable, and bound proof record;
- `installed/<application-id>/<format>/installation.json`: publisher pin,
  accepted sequence high-water mark, retained releases and pending operation;
- the existing Flatpak deployment journal beneath that installation directory;
- optional OCI state/documents directories, only when no explicit paths were given.

Update authorization and both packages are retained before a trial can commit.
The application's durable generation record chooses the active release. A failure
after commit therefore selects the new package; failure before commit keeps the
previous generation. Close the application before updating, rolling back or
recovering. An unfinished delivery requires explicit recovery:

```sh
cage release recover io.github.Pelagians.Cage.SumatraPDF \
  --key publisher-public.pem --format flatpak
```

Recovery re-verifies retained signatures/bytes and existing package journals; it
never restores a prefix snapshot over live settings or documents. Changed or
foreign deployment identities are refused before executing an application helper.
For AppImage and OCI, the shared committed state already chooses the retained
package; recovery reconciles the delivery ledger. Retained run/rollback/recovery
operations require no network connection. Interrupted downloads retain only an
unverified `.partial`; retry restarts that private partial, verifies size/hash,
then atomically promotes it. Completed cached assets are never truncated.

Rollback preserves the previous generation's settings and carries the **latest
qualified documents** forward. Newer settings remain in the retained newer
prefix. Legacy snapshots, failed candidates, old packages, image IDs and signed
release history are not automatically pruned. Existing storage controls protect
the default release cache; `cage storage status --package-dir CUSTOM_CACHE`
reports custom caches and pending recovery. Keep the ledger, public key, cached
artifacts and application state when making a recovery backup.

Accepted release sequences only increase for an installed publisher/application/
format. A stale update or publisher-key change is refused before downloading its
payload. Explicit rollback can select retained signed history without lowering
the sequence high-water mark. A failed trial also retains its accepted sequence;
use recovery and retained rollback, then a higher-sequence corrected release.
Deleting/restoring the local ledger changes what the client can know about past
sequences. There is no online freshness authority, automatic key rotation or
revocation lookup, background updater, or claim that a fresh client knows which
valid signed release is newest. Existing local/native tools remain explicit escape
hatches and are not made signature-enforcing by this optional client.

## Create a publisher release

Keep publisher private keys outside the public release directory. Private keys
must be unencrypted Ed25519 PKCS8 PEM files readable only by their owner. Key
creation refuses to replace either output:

```sh
mkdir -m 700 publisher-keys
cage release keygen --private-key publisher-keys/private.pem \
  --public-key publisher-keys/public.pem
```

Build/export with the existing recipes. Run the real application qualification
against both pinned versions. Current proof records bind package hashes (or
immutable OCI image IDs), architecture, page size, managed identities, actual
settings, save/relaunch, update and rollback assertions. Old proof records lacking
exact-byte bindings must be regenerated; a build result alone cannot authorize
a trusted release.

A producer spec uses one version and sequence across its artifacts. Paths are
relative to the spec file, or absolute. Include up to six distinct Linux
format/architecture pairs. Packages must have unique plain filenames; their
export receipts remain adjacent. Plans must agree on the desktop application ID
and recipe application name/version. Existing architecture-specific recipe names
(such as Notepad++'s ARM64 recipe) use separate release envelopes; the client still
installs each under the shared desktop application ID. For example:

```json
{
  "sequence": 1,
  "sourceRevision": "REPLACE_WITH_THE_40_OR_64_HEX_SOURCE_REVISION",
  "artifacts": [
    {"format": "flatpak", "path": "SumatraPDF-3.6-x86_64.flatpak", "evidence": "flatpak-proof/result.json"},
    {"format": "appimage", "path": "SumatraPDF-3.6-x86_64.AppImage", "evidence": "appimage-proof/result.json"},
    {"format": "oci", "image": "localhost/sumatra:3.6", "path": "SumatraPDF-3.6-x86_64.oci.tar", "evidence": "oci-proof/result.json"}
  ]
}
```

```sh
cage release create producer-spec.json --private-key publisher-keys/private.pem \
  --output public/3.6/release.json
```

The producer derives application/runtime/recipe identities from the existing
export receipts or embedded OCI metadata. `sourceRevision` is a publisher-declared
source revision, not an independently attested build. OCI archive paths must be
absent: Cage creates the archive from the inspected immutable image ID, retaining
an interrupted producer `.partial` for diagnosis. Other assets are staged with
independent copies/reflinks, or reused if already beside the output. Changed or
colliding assets and existing manifest outputs are refused.

The output is a `cage.release/v1` manifest and `release.json.sig`, signing the exact
manifest bytes with Ed25519 and the domain prefix `Cage trusted release v1\0`.
The manifest binds package sizes/hashes, original receipts/plans, recipe digests,
source revision, publisher fingerprint, sequence, qualification record hashes,
runtime page-size capabilities and separately observed test page sizes. Evidence
is the publisher's test assertion, not independent third-party certification.
Signature/schema checks precede payload download; package hashes and qualification
evidence are verified before deployment.
Flatpak releases additionally bind the exported OSTree commit; an unrelated
installed commit is refused before any state helper runs.

Serve the manifest, its `.sig` and referenced assets on ordinary HTTPS static
hosting, or distribute the directory offline. No account, catalog service or
Pelagian infrastructure is required. Cross-origin redirects, credential-bearing
URLs, path traversal and oversized payloads are refused. HTTP is accepted only
on loopback for local qualification. This command creates files; it does not
publish them or fulfill third-party source/license distribution obligations.

## Qualification scope

The existing onboarding/update workflows exercise trusted delivery for the two
pinned portable applications on native x86_64 and ARM64. They reuse existing
exports and application drivers, then test signed loopback HTTP installation,
update, menu relaunch, rollback, preserved settings/documents, and offline cached
inspection. Unit tests additionally exercise real signatures, bad keys, altered
metadata/payloads, stale sequences, interrupted downloads, low space, unsafe paths,
wrong architectures, runtime changes and interruptions around the durable commit.
CI signing identities are ephemeral and private keys are excluded from artifacts.
Both pinned applications passed Flatpak and AppImage delivery on x86_64 and
ARM64 after repairing the ARM64EC translator shutdown lock. The proofs retain
normal-exit, settings, document and rollback checks. See the
[qualification report](trusted-release-qualification.md) for exact source and
CI evidence, container results and remaining hardware boundaries.

These remain per-application portable Wine proofs. Registry conversion, runtime
upgrades, arbitrary legacy imports, macOS exports, automatic remote discovery and
unqualified Windows applications are outside this release. ARM64 CI's 4 KiB
results do not replace a final 16 KiB Asahi hardware qualification. The existing
Asahi evidence and local storage restrictions remain separately documented.

Signatures authenticate immutable delivered artifacts. They do not authenticate
later edits inside a mutable Wine prefix, installed plugins or the local user
account. The qualified recipes disable their own application updaters; existing
filesystem, network and desktop trust boundaries still apply.

Implementation references:
[Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/),
[Flatpak commit inspection](https://docs.flatpak.org/en/latest/flatpak-command-reference.html),
[OCI archive export](https://docs.podman.io/en/latest/markdown/podman-save.1.html).

See [qualification results and remaining limits](trusted-release-qualification.md).
