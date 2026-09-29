#!/usr/bin/env bash
# Exercise ordered root/application operations against an actual Cage image.
set -Eeuo pipefail
engine=${CONTAINER_ENGINE:-docker}
image=${1:?qualified candidate runtime image required}
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/workspace" "$scratch/dist"
cat > "$scratch/workspace/recipe.cage.yaml" <<'YAML'
schemaVersion: cage.app/v0
name: ordered-runtime-smoke
version: "1"
runtime:
  provider: wine
  version: "11.0"
  network: none
modules:
  - type: script
    run: |
      test "$(id -un)" = root
      install -d -o abc -g abc /etc/vendor-app
      printf 'captured\n' > /etc/vendor-app/config
      chown abc:abc /etc/vendor-app/config
      printf 'discarded\n' > /tmp/cage-undeclared
    outputs: [/etc/vendor-app]
  - type: registry
    changes:
      - action: set
        key: HKCU\Software\CageIntegration
        name: Ordered
        type: string
        value: "yes"
  - type: check
    command:
      run: 'test "$(id -un)" = abc && wine reg query "HKCU\Software\CageIntegration" /v Ordered'
launch:
  entrypoint: C:/windows/system32/cmd.exe
  args: [/c, exit, "0"]
YAML

label=$($engine image inspect --format '{{index .Config.Labels "org.pelagian.cage.root-build-operations"}}' "$image")
test "$label" = v1
test "$($engine image inspect --format '{{json .Config.Entrypoint}}' "$image")" = '["/init"]'
base_init=$($engine run --rm --entrypoint sha256sum "$image" /init | cut -d ' ' -f1)

python3 -m cage build "$scratch/workspace/recipe.cage.yaml" \
  --workspace "$scratch/workspace" --output "$scratch/dist" \
  --engine "$engine" --runtime-image "$image" --build-timeout 900 > "$scratch/build.json"
bundle=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bundle"])' "$scratch/build.json")
python3 -m cage bundle verify "$bundle" > "$scratch/verified.json"
test -s "$bundle/linux-state.tar"
test -d "$bundle/prefix/drive_c"
test ! -e "$bundle/prefix/dosdevices/z:"
test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["outputs"][0])' "$bundle/metadata/linux-state.json")" = /etc/vendor-app
test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["baseImage"])' "$bundle/metadata/linux-state.json")" = \
  "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["qualifiedBaseImage"])' "$bundle/build/build-plan.json")"

python3 -m cage run "$bundle" --graphics headless --engine "$engine" --timeout 180 > "$scratch/run.json"
run_image=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["runtimeImage"])' "$scratch/run.json")
test "$($engine image inspect --format '{{json .Config.Entrypoint}}' "$run_image")" = '["/init"]'
test "$($engine image inspect --format '{{index .Config.Labels "io.cage.linux-state"}}' "$run_image")" = \
  "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["derivedRuntimeImage"])' "$bundle/metadata/linux-state.json")"

python3 -m cage export oci "$bundle" --tag cage-ordered-integration:local \
  --engine "$engine" --graphics headless --timeout 900 > "$scratch/export.json"
for candidate in "$run_image" cage-ordered-integration:local; do
  test "$($engine run --rm --entrypoint cat "$candidate" /etc/vendor-app/config)" = captured
  ! $engine run --rm --entrypoint test "$candidate" -e /tmp/cage-undeclared
  test "$($engine run --rm --entrypoint sha256sum "$candidate" /init | cut -d ' ' -f1)" = "$base_init"
  test "$($engine image inspect --format '{{json .Config.Entrypoint}}' "$candidate")" = '["/init"]'
done
printf 'Ordered runtime integration: PASS engine=%s image=%s bundle=%s\n' "$engine" "$image" "$bundle"
