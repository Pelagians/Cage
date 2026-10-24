#!/usr/bin/env python3
"""Derive an update fixture from the shared recipe; pin official release bytes."""
from pathlib import Path
import hashlib
import json
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.manifest import load_manifest
from core.media import stage_media

VERSION = '8.8.9'
SHA256 = '4db7d6ae535eb6315e1005137344664cab341555ada9b073644bdea53070e628'
# Published by the application project:
# https://github.com/notepad-plus-plus/notepad-plus-plus/releases/tag/v8.8.9


def main():
    source = ROOT / ('sources/npp.' + VERSION + '.portable.x64.zip')
    if not source.exists():
        temporary = source.with_suffix('.partial')
        source.parent.mkdir(parents=True, exist_ok=True)
        url = 'https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v' + VERSION + '/' + source.name
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open('xb') as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 128 * 1024 * 1024:
                    raise ValueError('update archive exceeds quota')
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
            raise ValueError('update source checksum mismatch; partial retained')
        temporary.replace(source)
    if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != SHA256:
        raise ValueError('update source checksum mismatch')
    staging = ROOT / 'sources/notepadplusplus-update'
    if not staging.exists():
        stage_media(source, name='notepadplusplus-update', workspace=ROOT)
    destination = ROOT / 'dist/update-recipes'
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('notepadplusplus-portable', 'notepadplusplus-portable-arm64'):
        recipe = ROOT / 'recipes' / (name + '.cage.yaml')
        original = load_manifest(recipe)
        text = recipe.read_text().replace('8.8.8', VERSION).replace(original.sources[0].sha256, SHA256)
        text = text.replace('sources/notepadplusplus-portable/media', 'sources/notepadplusplus-update/media')
        generated = destination / (name + '.cage.yaml')
        generated.write_text(text)
        load_manifest(generated)
    print(json.dumps({'version': VERSION, 'sha256': SHA256, 'recipes': str(destination)}))


if __name__ == '__main__':
    main()
