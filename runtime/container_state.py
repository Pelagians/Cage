"""Opt-in generation adapter around the existing Wine container launch script.

The legacy hosted/CFW/Proton launch path stays intact unless a Wine recipe
explicitly declares desktop.updates and requests managed persistence.
"""
from __future__ import annotations

import base64
import json
import hashlib
import os
from pathlib import Path
import sys

# -I intentionally excludes the current directory and host Python packages.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from . import desktop_launch as state
except ImportError:
    import desktop_launch as state


def managed_plan(bundle, image=None):
    bundle = Path(bundle)
    manifest = json.loads((bundle / 'manifest.cage.json').read_text())
    graph = json.loads((bundle / 'metadata/graph.json').read_text())
    desktop = manifest.get('desktop', {})
    if not desktop.get('updates'):
        raise state.DesktopError('persistent generation management requires desktop.updates')
    state.validate_update_policy(desktop['updates'])
    runtime = graph['runnerRuntime']
    if runtime.get('launcher') != 'wine' or runtime.get('runnerUrl'):
        raise state.DesktopError('managed container updates currently require builtin Wine; external runners/Proton retain their existing workflows')
    environment = {**((manifest.get('compatibility') or {}).get('env') or {}),
                   **(graph.get('launch', {}).get('env') or {})}
    if any(key in environment for key in ('WINEPREFIX', 'CAGE_MANAGED_PREFIX', 'CAGE_STATE', 'CAGE_BUNDLE')):
        raise state.DesktopError('managed state paths cannot be overridden by recipe environment')
    selected_image = image or runtime['image']
    import re
    if not re.search(r'(?:@|^)sha256:[a-f0-9]{64}$', selected_image):
        raise state.DesktopError('managed updates require a digest-pinned container image')
    inventory = state.inventory_tree(bundle / 'prefix')
    return {'schemaVersion': 'cage.desktop-export-plan/v0', 'desktop': desktop,
            'state': {'managerVersion': 1,
                      'launcherSha256': hashlib.sha256(Path(state.__file__).read_bytes()).hexdigest(),
                      'adapterSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            'application': graph.get('application', {}), 'launch': graph['launch'],
            'seedDigest': state.digest_json(inventory),
            'target': {'runtime': runtime, 'image': image or runtime['image']}}


def run(plan, script, arguments):
    action = os.environ.get('CAGE_STATE_ACTION', 'launch')
    if arguments[:1] and arguments[0] in {'--cage-update', '--cage-rollback', '--cage-state-info'}:
        action, arguments = arguments[0][7:], arguments[1:]
    if arguments[:1] == ['--']:
        arguments = arguments[1:]
    if action not in {'launch', 'update', 'rollback', 'state-info'}:
        raise state.DesktopError('unknown container state action')
    seed = Path(os.environ.get('CAGE_BUNDLE', '/opt/cage/bundle')) / 'prefix'
    root = Path(os.environ.get('CAGE_STATE', '/var/lib/cage/state')) / plan['desktop']['id']
    identity = state.plan_identity(plan)
    base = root.parent
    if (base / 'prefix').exists() and not (root / 'state.json').exists():
        raise state.DesktopError('untracked legacy container prefix retained; qualify an explicit migration before enabling managed generations')
    with state.lifecycle_lock(root) as lock_fd:
        if action == 'state-info':
            print(json.dumps({'state': state._read_generations(root), 'packageIdentity': identity}, indent=2))
            return 0
        inventory = state.inventory_tree(seed)
        if state.digest_json(inventory) != plan['seedDigest']:
            raise state.DesktopError('container seed changed after planning')
        state.assert_quiescent(root, 'wineserver', os.environ)
        prefix, pending = state.prepare_generation(seed, inventory, root, identity, plan, action)
        environment = {**os.environ, 'WINEPREFIX': str(prefix), 'CAGE_MANAGED_PREFIX': str(prefix)}
        result = state._run_application(['/bin/bash', '-c', script, 'cage-managed', *arguments],
                     'wineserver', environment, seed.parent, root, locked=True, lock_fd=lock_fd)
        if result == 0 and pending:
            state.commit_generation(root, pending)
        return result


if __name__ == '__main__':
    try:
        if sys.argv[1] == '--plan-b64':
            plan = json.loads(base64.b64decode(sys.argv[2]))
            script = base64.b64decode(sys.argv[3]).decode()
            arguments = sys.argv[4:]
        else:
            plan = json.loads(Path(sys.argv[1]).read_text())
            script = Path(sys.argv[2]).read_text()
            arguments = sys.argv[3:]
        raise SystemExit(run(plan, script, arguments))
    except (state.DesktopError, OSError, ValueError, KeyError) as exc:
        print('Cage container state: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
