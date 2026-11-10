# Cage

Cage packages Windows applications so you can build and run them on Linux
with Wine or Proton. Start with a recipe that describes where the app comes
from, what it needs, and how to launch it. Cage builds a runnable bundle
with the app's Wine environment and a record of its sources and versions.

Use Cage when you need to rebuild or deploy the same Windows app across
Linux machines. You can run a bundle directly with Cage or export it as an
OCI container image. Compatibility depends on the app and runtime, and
Cage is currently in alpha.

## Try it with 7-Zip

This example uses x86-64 Linux, Python 3.11 or newer, Git, and a working
Docker installation. It downloads the runtime and installs 7-Zip from
Chocolatey, so the first build needs network access and can take a while.

From a clean checkout, install Cage into a virtual environment:

```bash
git clone https://github.com/Pelagians/Cage.git
cd Cage
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Build the bundle, verify it, and run the 7-Zip command-line executable
without opening a desktop session:

```bash
cage build recipes/7zip.cage.yaml --engine docker --output dist
cage bundle verify dist/7zip-0.1.0
cage run dist/7zip-0.1.0 --engine docker --graphics headless \
  --entrypoint 'C:/Program Files/7-Zip/7z.exe' --timeout 180
```

The [public package workflow](.github/workflows/chocolatey-public-package-proof.yml)
checks this build, verification, and headless launch path in CI.

## Build your own bundle

- [Recipe specification](docs/spec-v0.md) and [build steps](docs/ordered-modules.md)
  explain how to describe an app, its dependencies, and its launch command.
- [Usage reference](docs/usage-reference.md) covers runtime selection, private
  installers, GUI sessions, OCI export, and Kubernetes manifests.
- [Desktop exports](docs/desktop-exports.md) and [AppImage exports](docs/appimage-exports.md)
  cover desktop packaging and its current limitations.
- [Documentation index](docs/README.md) includes architecture, development,
  trusted releases, updates, and rollback.

## Maintained by Pelagian

Cage runs independently of the Pelagian platform.

## License

Open source — available under the MIT License.
