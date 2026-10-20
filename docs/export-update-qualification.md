# Export update qualification

This report separates source checks from packaged GUI behavior. The update
workflow is limited to the qualified portable Notepad++ profile; it does not
certify arbitrary application, runtime, registry, CFW or Proton migrations.

## Source validation

The isolated Python 3.13 suite passes **492 tests and 185 subtests**, including
wheel construction and reproducible Chocolatey smoke-package checks. Four
Docker-specific fixtures now explicitly model Docker instead of accidentally
testing the Asahi host's Docker-to-Podman alias; the dedicated alias-normalization
test remains active. The unchanged CFW checkout passes **49 tests**.

The transaction tests exercise real subprocesses and saved prefix contents,
including failure before commit, failed application exit, cleanup failure,
concurrent launch, a SIGKILLed launcher with a surviving child, contract-only
updates, legacy-state adoption, incompatible profiles, and document deletion.
Deployment recovery chooses the artifact matching committed state, including
an error after the state pointer changed. Host package tests distinguish local
hash integrity from publisher authentication.

## Runtime validation

Source revision: `bf313f33ebbfc05edd27ab50e604588582575e3e`.

All three local GUI proofs passed on the Apple M1 Asahi host with a **16,384-byte
kernel page size**. Each proof used fresh private state and ran five sessions:
baseline 8.8.8, update to 8.8.9, updated relaunch, rollback to 8.8.8, and rollback
relaunch. Checks compared executables with both pinned source archives, changed
the real editor zoom preference, saved an external Unicode-named document,
and carried the latest prefix document through rollback. The bundled self-updater
was absent. Original generations remained intact throughout each proof.

| Adapter | Local result | Evidence under `dist/appimage-evidence/` |
| --- | --- | --- |
| Native Wine ARM64EC/FEX container | Passed | `asahi-final-updates-container/result.json` |
| Flatpak | Passed | `asahi-final-updates-flatpak/result.json` |
| AppImage, native FUSE execution | Passed | `asahi-final-updates-appimage/result.json` |

Each evidence directory includes screenshots and per-session logs. AppImage
integration was installed, launched through its desktop entry, and uninstalled
without deleting state. Flatpak used an isolated installation; its test-only
wrapper set a private `XDG_DATA_HOME` **inside** the sandbox because Flatpak resets
reserved XDG variables supplied from the host. The packaged entry point and
generation manager were used. Normal user application data was untouched.

After successful evidence capture, only the newly created Flatpak and AppImage
proof prefixes were discarded to limit disk use; the private Flatpak test
installation and redundant package cache were also removed. Their result records,
screenshots, documents and package recovery metadata remain. The container proof
prefixes remain. This is proof-harness cleanup, not automatic pruning in user
installations: failed candidates and user generations are still retained.

Native CI at the same source revision:

- [Update and rollback proof](https://github.com/Pelagians/Cage/actions/runs/39471937374):
  x86_64 Flatpak and AppImage consumer proofs passed; ARM container proof passed.
  The aarch64 desktop job was still running when this report was recorded.
- [AppImage regression proof](https://github.com/Pelagians/Cage/actions/runs/39471937317):
  passed, including both architecture exports and consumer checks.
- [x86_64 Flatpak regression proof](https://github.com/Pelagians/Cage/actions/runs/39471937861):
  passed.
- [ARM regression proof](https://github.com/Pelagians/Cage/actions/runs/39471937323):
  retry in progress after the initial run failed fetching Fedora mirror metadata
  with HTTP 503. This is not recorded as a successful current-revision regression
  run. The preceding revision's ARM regression run passed.

## Retained local packages

The following files are local, unsigned proof artifacts in `dist/`, with adjacent
Cage JSON receipts. Their packaged generation-manager hash matches the current
source. Hashes identify the local bytes; they do not authenticate a publisher.

| Package | SHA-256 |
| --- | --- |
| `update-final-8.8.8-aarch64.AppImage` | `5957d4cf82103eb22dc54a764b073620ec163ba8c890e800e21ca792713e68f4` |
| `update-final-8.8.9-aarch64.AppImage` | `dc57448ea4d0612ae28844fd7a7c7476e3beec9de887e2fe9a4fc16fe6c069d7` |
| `update-final-8.8.8-aarch64.flatpak` | `e63b7cb3e58bf33f822f312aab126ff526194d1ddd3e1d02a2a5c60cfb29f3b8` |
| `update-final-8.8.9-aarch64.flatpak` | `30724480d6f20752e5139b51a174eee80415ea837c9b8c29ed20e8d129f8943e` |

The native container bundles are under `dist/update-final-container/` and use the
unchanged pinned carrier digest
`sha256:2b18664b3b240d2f0daf77f046781670ca2f26b7f0458d9374d4b65754489587`.
Superseded unpacked builds and duplicate prototype/CI packages were removed;
export receipts, inventories, qualification evidence and the current package pair
were retained. No user settings or documents were removed.

## Qualification limits

This qualifies the tested Notepad++ profile and version pair. It does not qualify
registry migrations, arbitrary plugins or applications, Wine/FEX runtime changes,
system Flatpak installations, signed release distribution, or external Proton/CFW
updates. The builtin Wine container adapter has source/contract coverage; the
real container GUI update proof uses the native ARM64EC/FEX adapter. The OCI
export launcher shares that manager, but a separate standalone OCI-image GUI
update/rollback qualification has not been performed.
