"""Versioned recipe capabilities; pure normalization and target planning.

Host grants and availability are separate. This module neither changes native
permissions nor opens devices. v0 callers do not enter this contract.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import PurePosixPath

SCHEMA = 'cage.app/v1'
TARGETS = {'oci', 'flatpak', 'appimage'}
BASES = {'home', 'xdg-desktop', 'xdg-documents', 'xdg-download', 'xdg-music',
         'xdg-pictures', 'xdg-videos', 'xdg-config', 'xdg-cache', 'xdg-data', 'absolute'}
COMMON = {'id', 'kind', 'reason', 'required'}
FIELDS = {
    'filesystem': {'location', 'access', 'create', 'wineDrive'}, 'network': set(),
    'display': {'backend'}, 'device-class': {'class', 'hotplug'},
    'usb': {'access', 'interfaces', 'allow', 'exclude', 'presence', 'hotplug'},
    'audio': {'access'}, 'dbus': {'bus', 'talk', 'own'},
    'host-service': {'service'}, 'portal': {'interface'},
}


class CapabilityError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _object(value, fields, label, required=()):
    if not isinstance(value, dict) or set(value) - fields or set(required) - set(value):
        raise CapabilityError(f'{label}: expected fields {sorted(fields)}; required {sorted(required)}')
    return copy.deepcopy(value)


def _string(value, label, pattern=None, limit=4096):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise CapabilityError(f'{label}: invalid string')
    if pattern and not re.fullmatch(pattern, value):
        raise CapabilityError(f'{label}: malformed value')
    return value


def _enum(value, choices, label):
    if not isinstance(value, str) or value not in choices:
        raise CapabilityError(f'{label}: expected one of {sorted(choices)}')
    return value


def _bool(value, label):
    if type(value) is not bool:
        raise CapabilityError(f'{label}: expected boolean')
    return value


def _set(value, label, allowed=None, nonempty=True):
    if not isinstance(value, list) or (nonempty and not value) or not all(isinstance(x, str) for x in value):
        raise CapabilityError(f'{label}: expected string list')
    if len(value) != len(set(value)) or (allowed is not None and set(value) - allowed):
        raise CapabilityError(f'{label}: duplicate or unknown value')
    return sorted(value)


def location(value):
    result = _object(value, {'base', 'path'}, 'location', ['base'])
    base = _enum(result['base'], BASES, 'location.base')
    path = result.get('path')
    if base == 'absolute' and path is None:
        raise CapabilityError('absolute location requires path')
    if path is not None:
        _string(path, 'location.path')
        parts = path.split('/')
        if base == 'absolute':
            if not path.startswith('/'):
                raise CapabilityError('absolute location requires absolute path')
            parts = parts[1:]
        elif path.startswith('/'):
            raise CapabilityError('symbolic location requires relative path')
        if any(p in ('', '.', '..') for p in parts) and not (base == 'absolute' and path == '/'):
            raise CapabilityError('unsafe location path components')
    return result


def _match(value):
    r = _object(value, {'vendor', 'product', 'productRange', 'class', 'subclass', 'serial'}, 'usb.match')
    if not ('vendor' in r or 'class' in r):
        raise CapabilityError('USB match needs vendor or class')
    for k in ('vendor', 'product', 'class', 'subclass'):
        if k in r:
            _string(r[k], 'usb.' + k, '[0-9a-f]{4}' if k in ('vendor', 'product') else '[0-9a-f]{2}')
    if ('product' in r or 'productRange' in r) and 'vendor' not in r:
        raise CapabilityError('USB product requires vendor')
    if 'subclass' in r and 'class' not in r:
        raise CapabilityError('USB subclass requires class')
    if 'productRange' in r:
        if 'product' in r:
            raise CapabilityError('USB product and range are exclusive')
        bounds = _object(r['productRange'], {'first', 'last'}, 'USB range', ['first', 'last'])
        for key in bounds:
            _string(bounds[key], 'USB range.' + key, '[0-9a-f]{4}')
        if int(bounds['first'], 16) > int(bounds['last'], 16):
            raise CapabilityError('reversed USB range')
        r['productRange'] = bounds
    if 'serial' in r:
        _string(r['serial'], 'USB serial')
    return r


def normalize(app_id, execution, permissions, desktop_id=None):
    app_id = _string(app_id, 'id', r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){2,}', 180)
    if desktop_id is not None and desktop_id != app_id:
        raise CapabilityError('id must equal desktop.id')
    execution = _object(execution, {'environment', 'targets', 'fallbacks'}, 'execution', ['environment', 'targets'])
    _enum(execution['environment'], {'local-desktop', 'headless', 'remote-session'}, 'execution.environment')
    execution['targets'] = _set(execution['targets'], 'execution.targets', TARGETS)
    permissions = _object(permissions, {'requests'}, 'permissions', ['requests'])
    if not isinstance(permissions['requests'], list) or len(permissions['requests']) > 256:
        raise CapabilityError('permissions.requests must be a bounded list')
    requests, ids, singletons, drives = [], set(), set(), set()
    for raw in permissions['requests']:
        if not isinstance(raw, dict) or not isinstance(raw.get('kind'), str) or raw.get('kind') not in FIELDS:
            raise CapabilityError('unknown permission kind')
        kind = raw['kind']
        r = _object(raw, COMMON | FIELDS[kind], 'permission', ['id', 'kind', 'reason'])
        rid = _string(r['id'], 'permission.id', '[a-z][a-z0-9-]{0,62}')
        _string(r['reason'], 'permission.reason', limit=240)
        if rid in ids:
            raise CapabilityError('duplicate permission id: ' + rid)
        ids.add(rid)
        r['required'] = _bool(r.get('required', False), 'permission.required')
        if kind in ('network', 'display'):
            if kind in singletons:
                raise CapabilityError('duplicate singleton: ' + kind)
            singletons.add(kind)
        try:
            if kind == 'filesystem':
                r['location'] = location(r['location'])
                _enum(r['access'], {'read-only', 'read-write'}, 'filesystem.access')
                r['create'] = _bool(r.get('create', False), 'filesystem.create')
                if r['create'] and r['access'] != 'read-write':
                    raise CapabilityError('read-only location cannot be created')
                if 'wineDrive' in r:
                    drive = _string(r['wineDrive'], 'wineDrive', '[A-Z]')
                    if drive in drives or drive in {'C', 'Z'}:
                        raise CapabilityError('duplicate/reserved wine drive')
                    drives.add(drive)
            elif kind == 'display':
                _enum(r['backend'], {'x11', 'wayland'}, 'display.backend')
            elif kind == 'device-class':
                _enum(r['class'], {'gpu', 'usb', 'input', 'all', 'kvm', 'shm'}, 'device.class')
                r['hotplug'] = _enum(r.get('hotplug', 'startup-only'), {'required', 'startup-only'}, 'hotplug')
            elif kind == 'usb':
                _enum(r['access'], {'direct', 'portal'}, 'usb.access')
                r['interfaces'] = _set(r['interfaces'], 'usb.interfaces', {'usb', 'hidraw'})
                if r['access'] == 'portal' and r['interfaces'] != ['usb']:
                    raise CapabilityError('portal requires exactly usb interface')
                for field in ('allow', 'exclude'):
                    matches = r.get(field, [])
                    if not isinstance(matches, list) or (field == 'allow' and not matches) or len(matches) > 256:
                        raise CapabilityError('USB selector list missing or too large')
                    r[field] = sorted((_match(m) for m in matches), key=digest)
                    if len({digest(m) for m in r[field]}) != len(r[field]):
                        raise CapabilityError('duplicate USB selector')
                r['presence'] = _enum(r.get('presence', 'optional'), {'optional', 'required'}, 'presence')
                r['hotplug'] = _enum(r.get('hotplug', 'required'), {'required', 'startup-only'}, 'hotplug')
                if r['presence'] == 'required' and not r['required']:
                    raise CapabilityError('required presence needs required capability')
            elif kind == 'audio':
                _enum(r['access'], {'playback-and-capture', 'playback', 'capture'}, 'audio.access')
            elif kind == 'dbus':
                _enum(r['bus'], {'session', 'system'}, 'dbus.bus')
                for field in ('talk', 'own'):
                    r[field] = _set(r.get(field, []), 'dbus.' + field, nonempty=False)
                    for name in r[field]:
                        _string(name, 'dbus name', r'[A-Za-z_-][A-Za-z0-9_-]*(?:\.[A-Za-z_-][A-Za-z0-9_-]*)+(?:\.\*)?')
                if not r['talk'] and not r['own']:
                    raise CapabilityError('empty bus policy')
            elif kind == 'host-service':
                _enum(r['service'], {'printing', 'smart-card', 'ssh-agent', 'gpg-agent'}, 'service')
            elif kind == 'portal':
                _enum(r['interface'], {'file-chooser', 'open-uri', 'print', 'camera', 'notifications'}, 'portal.interface')
        except KeyError as exc:
            raise CapabilityError(f'{rid}: missing {exc.args[0]}') from exc
        requests.append(r)
    fallbacks, pairs = [], set()
    raw_fallbacks = execution.get('fallbacks', [])
    if not isinstance(raw_fallbacks, list) or len(raw_fallbacks) > 256:
        raise CapabilityError('invalid fallbacks')
    by_id = {r['id']: r for r in requests}
    for raw in raw_fallbacks:
        f = _object(raw, {'target', 'request', 'grant'}, 'fallback', ['target', 'request', 'grant'])
        target = _enum(f['target'], set(execution['targets']), 'fallback.target')
        rid = _string(f['request'], 'fallback.request')
        if (target, rid) in pairs or rid not in by_id:
            raise CapabilityError('duplicate/unresolved fallback')
        pairs.add((target, rid))
        req = by_id[rid]
        if req['kind'] != 'usb' or req['access'] != 'direct':
            raise CapabilityError('fallback requires direct USB request')
        grant = _object(f['grant'], {'kind', 'class'}, 'fallback.grant', ['kind', 'class'])
        if grant['kind'] != 'device-class' or grant['class'] not in ('all', 'usb'):
            raise CapabilityError('unsupported fallback grant')
        if grant['class'] == 'usb' and 'hidraw' in req['interfaces']:
            raise CapabilityError('raw USB fallback cannot satisfy hidraw')
        fallbacks.append(f)
    if any(r['kind'] == 'usb' for r in requests) and any(r['kind'] == 'device-class' and r['class'] in {'all', 'usb'} for r in requests):
        raise CapabilityError('broad device grant conflicts with selected USB; use explicit substitution')
    execution['fallbacks'] = sorted(fallbacks, key=lambda f: (f['target'], f['request']))
    return {'id': app_id, 'execution': execution, 'permissions': {'requests': sorted(requests, key=lambda r: r['id'])}}


def compile_capabilities(manifest, target, *, decisions=None, bindings=None):
    """Compile intent only. Successful host preflight is still required to run."""
    manifest = manifest.to_dict() if hasattr(manifest, 'to_dict') else manifest
    contract = normalize(manifest.get('id'), manifest.get('execution'), manifest.get('permissions'), manifest.get('desktop', {}).get('id'))
    if target not in contract['execution']['targets']:
        raise CapabilityError('target not selected by recipe')
    decisions, bindings = decisions or {}, bindings or {}
    ids = {r['id'] for r in contract['permissions']['requests']}
    if set(decisions) - ids or set(bindings) - ids or any(v not in ('allow', 'deny') for v in decisions.values()):
        raise CapabilityError('unresolved local decision/binding')
    network = any(r['kind'] == 'network' and decisions.get(r['id']) != 'deny' for r in contract['permissions']['requests'])
    records = []
    for original in contract['permissions']['requests']:
        request = copy.deepcopy(original)
        if request['id'] in bindings:
            if request['kind'] != 'filesystem':
                raise CapabilityError('only filesystem locations can be rebound')
            request['location'] = location(bindings[request['id']])
        kind, rid = request['kind'], request['id']
        supported = kind in {'filesystem', 'network'} or (kind == 'display' and request['backend'] == 'x11')
        if kind == 'filesystem':
            loc = request['location']
            if loc['base'] == 'absolute':
                path = PurePosixPath(loc['path'])
                supported = path != PurePosixPath('/') and not any(path == PurePosixPath(x) or PurePosixPath(x) in path.parents for x in ('/dev', '/proc', '/sys', '/run', '/app', '/usr', '/etc', '/var', '/opt'))
            if loc['base'] in {'home', 'xdg-data', 'xdg-cache', 'xdg-config'} and not loc.get('path'):
                supported = False  # Would include protected host policy/installation stores.
            if any(c in loc.get('path', '') for c in ':;,\\'):
                supported = False  # Native Flatpak filesystem suffixes cannot represent this safely.
        supported |= kind == 'device-class' and request['class'] == 'all' and (request['hotplug'] == 'startup-only' or network)
        grant, fallback = copy.deepcopy(request), None
        if not supported and decisions.get(rid) != 'deny':
            fallback = next((f for f in contract['execution']['fallbacks'] if f['target'] == target and f['request'] == rid), None)
            if fallback and fallback['grant']['class'] == 'all' and (request['hotplug'] == 'startup-only' or network):
                grant = {**request, 'enforcementGrant': fallback['grant']}
                supported = True
        if contract['execution']['environment'] != 'local-desktop':
            supported = False
        status = 'denied' if decisions.get(rid) == 'deny' else 'broader-accepted' if supported and fallback else 'exact' if supported else 'unsupported'
        records.append({'id': rid, 'requested': original, 'resolved': request, 'grant': grant if supported and status != 'denied' else None,
                        'enforcement': status, 'required': request['required'], 'fallback': fallback,
                        'availability': 'unknown', 'hostPreflightRequired': True})
    files = [r for r in records if r['resolved']['kind'] == 'filesystem']
    for i, first in enumerate(files):
        for second in files[i + 1:]:
            a, b = first['resolved'], second['resolved']
            if a['location']['base'] != b['location']['base']:
                continue  # Host preflight checks resolved aliases too.
            x, y = PurePosixPath(a['location'].get('path', '.')), PurePosixPath(b['location'].get('path', '.'))
            if x == y or x in y.parents or y in x.parents:
                if (first['enforcement'] == 'denied') != (second['enforcement'] == 'denied') or a['access'] != b['access']:
                    raise CapabilityError('overlapping filesystem grant defeats a denial/read-only scope')
    return {'schemaVersion': 'cage.capability-plan/v1', 'applicationId': contract['id'],
            'target': target, 'environment': contract['execution']['environment'],
            'contract': contract, 'contractDigest': digest(contract), 'requests': records,
            'launchAllowed': not any(r['required'] and r['enforcement'] in {'denied', 'unsupported'} for r in records),
            'baseline': 'cage.local-desktop/v1', 'networkScope': 'host-ip-and-abstract' if network else 'private',
            'qualification': 'planned-not-runtime-qualified'}


def require_supported(plan):
    bad = [r['id'] for r in plan['requests'] if r['required'] and r['enforcement'] in {'denied', 'unsupported'}]
    if bad:
        raise CapabilityError('required capability denied/unsupported: ' + ', '.join(bad))


def flatpak_permissions(plan):
    require_supported(plan)
    flags = ['--unshare=ipc', '--unshare=network']
    for item in plan['requests']:
        if not item['grant']:
            continue
        r = item['grant']; kind = r['kind']
        if kind == 'network': flags.append('--share=network')
        elif kind == 'display': flags.append('--socket=x11')
        elif kind == 'filesystem':
            loc = r['location']; path = loc.get('path', '')
            base = loc['base']
            path = path if base == 'absolute' else ('~' if base == 'home' else base) + ('/' + path if path else '')
            flags.append('--filesystem=' + path + (':ro' if r['access'] == 'read-only' else ':create' if r['create'] else ':rw'))
        elif kind == 'device-class' or item['fallback']:
            flags.append('--device=all')
    return flags
