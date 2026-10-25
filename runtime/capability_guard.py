"""Small stdlib-only pre-payload guard shipped with managed v1 exports."""
from __future__ import annotations
import configparser
import hashlib
import json
import os
from pathlib import Path


def policy_snapshot(text):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(text)
    result = {section: dict(parser[section]) for section in
              ('Context', 'Session Bus Policy', 'System Bus Policy', 'Environment', 'Policy') if parser.has_section(section)}
    if 'Environment' in result:
        # Host CLI supplies these after inspection; exclude the receipt itself
        # from its own digest. Recipes cannot declare this reserved namespace.
        result['Environment'] = {k:v for k,v in result['Environment'].items() if not k.startswith('CAGE_')}
        if not result['Environment']:result.pop('Environment')
    return result


def policy_digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def check(plan, *, environment=None, proc=Path('/proc'), flatpak_info=Path('/.flatpak-info')):
    if plan.get('state', {}).get('managerVersion') != 2:
        return
    env = os.environ if environment is None else environment
    if env.get('CAGE_MANAGED_V1') != '1':
        raise ValueError('v1 payload requires the trusted host Cage launch path')
    status = dict(line.split(':', 1) for line in (proc/'self/status').read_text().splitlines() if ':' in line)
    if (status.get('NoNewPrivs', '').strip() != '1' or int(status.get('CapEff', '1').strip(), 16) != 0
            or status.get('Seccomp', '').strip() != '2'):
        raise ValueError('required v1 privilege/syscall baseline is not established')
    if not env.get('CAGE_POLICY_DIGEST'):
        raise ValueError('missing managed effective policy receipt')
    for item in json.loads(env.get('CAGE_EXPECTED_FILES','[]')):
        info=Path(item['path']).stat()
        if (info.st_dev,info.st_ino)!=(item['device'],item['inode']):
            raise ValueError('folder changed between host inspection and namespace launch; reinspect')
    if plan.get('format') == 'flatpak':
        text = flatpak_info.read_text()
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        if parser.get('Application', 'name', fallback='') != plan['desktop']['id']:
            raise ValueError('native Flatpak application identity mismatch')
        if parser.get('Instance', 'app-commit', fallback='') != env.get('CAGE_EXPECTED_FLATPAK_COMMIT'):
            raise ValueError('native Flatpak deployment changed before launch')
        if parser.get('Instance', 'runtime-commit', fallback='') != plan['target']['platformCommit']:
            raise ValueError('native Flatpak runtime changed before launch')
        if policy_digest(policy_snapshot(text)) != env['CAGE_POLICY_DIGEST']:
            raise ValueError('native permissions changed before launch; reinspect instead of rewriting overrides')
    elif not plan.get('managedNamespace'):
        raise ValueError('v1 native payload lacks its managed namespace contract')
