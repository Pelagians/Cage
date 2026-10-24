#!/usr/bin/env python3
"""Derive pinned release/runtime variants from one shared application recipe."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.manifest import load_manifest, Manifest
from core.sources import prepare_portable_source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', choices=['wine', 'wine-arm64ec'], default='wine')
    args = parser.parse_args()
    original = load_manifest(ROOT / 'recipes/sumatrapdf-portable.cage.yaml').to_dict()
    releases = json.loads((ROOT / 'recipes/sumatrapdf-portable.releases.json').read_text())
    output = ROOT / 'dist/onboarding-recipes' / args.runtime
    output.mkdir(parents=True, exist_ok=True)
    for version, lock in releases.items():
        text = json.dumps(original).replace('3.6', version)
        payload = json.loads(text)
        payload['runtime']['provider'] = args.runtime
        payload['runtime']['version'] = '11.20' if args.runtime == 'wine-arm64ec' else '11.0'
        payload['sources'][0]['sha256'] = lock['archiveSha256']
        payload['modules'][0]['mappings'][0]['sha256'] = lock['executableSha256']
        # Normalized manifests include a compatibility schema marker; parsing
        # source recipes intentionally retains strict unknown-key validation.
        payload.get('compatibility', {}).pop('schemaVersion', None)
        manifest = Manifest.from_dict(payload)
        prepare_portable_source(manifest, workspace=ROOT)
        destination = output / (version + '.json')
        destination.write_text(json.dumps(payload, indent=2) + '\n')
        print(json.dumps({'version': version, 'runtime': args.runtime, 'recipe': str(destination)}), flush=True)


if __name__ == '__main__':
    main()
