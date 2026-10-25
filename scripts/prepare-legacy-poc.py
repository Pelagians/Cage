#!/usr/bin/env python3
"""Package historical Cage helpers for isolated migration qualification only."""
from pathlib import Path
import argparse
import contextlib
import hashlib
import json
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact import appimage, flatpak
from artifact.inspection import verify_bundle
from runtime import desktop_launch
from runtime.desktop_launch import copy_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('format', choices=['flatpak', 'appimage', 'container'])
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--flatpak-store', default='.cage/flatpak')
    parser.add_argument('--tool-cache', default='.cage/appimage-tools')
    parser.add_argument('--context-dir')
    args = parser.parse_args()
    fixture = ROOT / 'tests/fixtures/legacy-desktop'
    helper = fixture / 'runtime/desktop_launch.py'
    if args.format == 'container':
        assert verify_bundle(args.bundle)['valid']
        shutil.copytree(args.bundle, args.output, symlinks=True, copy_function=copy_file)
        metadata = args.output / 'metadata/native-launch.json'
        plan = json.loads(metadata.read_text())
        plan['state'] = {'schemaVersion': 'cage.desktop-state/v0'}
        plan['launcherSha256'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        shutil.copyfile(helper, args.output / 'metadata/cage-desktop-launch.py')
        metadata.write_text(json.dumps(plan, indent=2) + '\n')
        assert verify_bundle(args.output)['valid']
        print(json.dumps({'legacyTestFixture': True, 'bundle': str(args.output)}))
        return
    producer = flatpak if args.format == 'flatpak' else appimage
    name = 'create_' + args.format + '_export_plan'
    original = getattr(producer, name)
    def legacy_plan(*positional, **options):
        plan = original(*positional, **options)
        plan['state'].pop('managerVersion', None)
        plan['state']['schemaVersion'] = 'cage.desktop-state/v0'
        plan['state']['upgradePolicy'] = 'refuse-mismatch-retain-data'
        return plan
    with tempfile.TemporaryDirectory() as td, contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(desktop_launch, '__file__', str(helper)))
        stack.enter_context(patch.object(producer, name, side_effect=legacy_plan))
        if args.format == 'appimage':
            runtime = Path(td) / 'runtime'
            shutil.copytree(fixture / 'runtime', runtime)
            # Keep the historical lifecycle helpers intact while using the same
            # native transport and pinned runtime as the managed baseline.
            for name in ('appimage-tools.json', 'appimage_runtime.py'):
                shutil.copyfile(ROOT / 'runtime' / name, runtime / name)
            stack.enter_context(patch.object(appimage, 'ROOT', Path(td)))
        options = dict(output=args.output, store=args.flatpak_store, context_dir=args.context_dir)
        if args.format == 'appimage':options.update(allow_host_access=True, cache=args.tool_cache)
        result = getattr(producer, 'export_' + args.format)(args.bundle, **options)
        result['legacyTestFixture'] = {'revision': '10c295a', 'launcherSha256': hashlib.sha256(helper.read_bytes()).hexdigest()}
        print(json.dumps(result, indent=2))


if __name__ == '__main__':main()
