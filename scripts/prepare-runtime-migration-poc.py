#!/usr/bin/env python3
"""Bind shared recipe policy to exact exported/planned runtime transitions.

This only writes a candidate recipe. It does not certify a transition, modify
installed state or relax a runtime pin. Build, workflow proof and release signing
remain separate, using the existing builder, exporters and qualification driver.
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.manifest import load_manifest, Manifest
from runtime.desktop_launch import DesktopError, runtime_migration_rule, validate_update_policy


def read_plan(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise DesktopError('runtime transition inputs must be ordinary plan/receipt files')
    value = json.loads(path.read_text())
    value = value.get('plan', value)
    return value.get('managedState', value)


def prepare(recipe, pairs, output):
    manifest = load_manifest(Path(recipe))
    payload = manifest.to_dict()
    policy = payload['desktop']['updates']
    migrations = list(policy.get('runtimeMigrations', []))
    for previous_path, candidate_path in pairs:
        previous, candidate = read_plan(previous_path), read_plan(candidate_path)
        if (candidate.get('application') != {'name': manifest.name, 'version': manifest.version}
                or candidate.get('state', {}).get('managerVersion') != 1
                or candidate['desktop']['id'] != manifest.desktop['id']
                or any(candidate['desktop']['updates'][k] != policy[k] for k in ('profile', 'settings', 'documents'))):
            raise DesktopError('candidate plan and shared recipe application/data policy differ')
        rule = runtime_migration_rule(previous, candidate)
        if rule not in migrations:
            migrations.append(rule)
    policy['runtimeMigrations'] = migrations
    validate_update_policy(policy)
    payload.get('compatibility', {}).pop('schemaVersion', None)
    Manifest.from_dict(payload)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        handle.write(json.dumps(payload, indent=2) + '\n')
    return {'recipe': str(output), 'runtimeMigrations': migrations,
            'qualification': 'proposal only; rebuild and complete runtime migration proof before signing'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe')
    parser.add_argument('--pair', nargs=2, action='append', required=True, metavar=('BASELINE_PLAN', 'CANDIDATE_PLAN'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.recipe, args.pair, args.output), indent=2))


if __name__ == '__main__':
    main()
