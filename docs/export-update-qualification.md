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

Native x86_64/aarch64 CI and local Asahi 16 KB GUI qualification are in progress.
The dedicated `export-updates.yml` workflow builds the pinned 8.8.8/8.8.9 pair,
then checks installation, real preferences, external and prefix documents,
update/relaunch and rollback/relaunch. Completed run links and artifact hashes
will be added after the checks finish. Do not treat source-test success as a
completed runtime qualification.

Original user application data and earlier qualified artifacts are retained.
Only fresh proof state is used. Failed candidates are retained for recovery.
