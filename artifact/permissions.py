"""Native-first permissions inspection/adoption. Never writes Flatpak overrides."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from artifact import authority, releases as r
from core.capabilities import compile_capabilities, location, digest
from runtime.capability_guard import policy_snapshot, policy_digest
from runtime.desktop_launch import lifecycle_lock, _write_state_record


def _command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def installed(app, kind):
    from artifact import release_install as delivery
    owner, root, key = authority.registered(app, kind)
    record = delivery._read(delivery.installation(root, app, kind))
    if not record or record.get('pending'):
        raise r.ReleaseError('installation missing or pending recovery')
    if record['publisherKeySha256'] != owner['publisherKeySha256']:
        raise r.ReleaseError('installation and canonical authority differ')
    return record, delivery._selected(root, record, key, kind), root


def bindings_path(app, kind):
    return authority.authority_folder(app)/('bindings-' + kind + '.json')


def local_bindings(app, kind):
    path = bindings_path(app, kind)
    if not path.exists() and not path.is_symlink(): return {'bindings':{}, 'decisions':{}}
    value = r.parse(r.small(r.regular(path)))
    if value.get('schemaVersion') != 'cage.local-capability-bindings/v1' or value.get('applicationId') != app:
        raise r.ReleaseError('invalid local bindings; retained')
    return value


def applicable_inputs(recipe, local):
    """Retain revocations/bindings for historical releases without applying typos."""
    ids={request['id'] for request in recipe['permissions']['requests']}
    decisions,bindings=local.get('decisions',{}),local.get('bindings',{})
    if not isinstance(decisions,dict) or not isinstance(bindings,dict):raise r.ReleaseError('invalid retained local capability inputs')
    return {'decisions':{k:v for k,v in decisions.items() if k in ids},
            'bindings':{k:v for k,v in bindings.items() if k in ids}}


def native_snapshot(release):
    """Read actual native namespace metadata with a pinned runtime's cat, no app code."""
    entry = release['entry'];plan = entry['plan'];app = plan['desktop']['id'];target = plan['target']
    ref = 'app/' + app + '/' + target['architecture'] + '/stable'
    if _command(['flatpak','info','--user','--show-commit',ref]) != entry['flatpakCommit']:
        raise r.ReleaseError('native application commit is not the signed deployment')
    runtime = target['platform'] + '/' + target['architecture'] + '/' + target['branch']
    if _command(['flatpak','info','--user','--show-commit',runtime]) != target['platformCommit']:
        raise r.ReleaseError('native inspection runtime differs from qualified pin')
    # /usr is the verified native runtime, never the application's /app/bin.
    text = _command(['flatpak','run','--user','--commit='+entry['flatpakCommit'],'--runtime-commit='+target['platformCommit'],'--command=/usr/bin/cat',ref,'/.flatpak-info'])
    metadata = _command(['flatpak','run','--user','--commit='+entry['flatpakCommit'],'--runtime-commit='+target['platformCommit'],
                         '--command=/usr/bin/cat',ref,'/app/share/cage/'+app+'/desktop.json'])
    if json.loads(metadata) != plan:raise r.ReleaseError('installed native plan differs from signed release')
    snapshot = policy_snapshot(text)
    return {'policy':snapshot, 'digest':policy_digest(snapshot), 'ref':ref,'scope':'new-native-launch-snapshot'}


def _locations():
    home = Path.home()
    result = {'home':home,'xdg-data':Path(os.environ.get('XDG_DATA_HOME',home/'.local/share')),
              'xdg-cache':Path(os.environ.get('XDG_CACHE_HOME',home/'.cache')),
              'xdg-config':Path(os.environ.get('XDG_CONFIG_HOME',home/'.config'))}
    names = {'DESKTOP':'Desktop','DOCUMENTS':'Documents','DOWNLOAD':'Downloads','MUSIC':'Music','PICTURES':'Pictures','VIDEOS':'Videos'}
    values = {}
    config = result['xdg-config']/'user-dirs.dirs'
    if config.is_file():
        for name,path in re.findall(r'^XDG_([A-Z]+)_DIR="([^"\n]*)"\s*$',config.read_text(),re.M):
            path = path.replace('${HOME}',str(home)).replace('$HOME',str(home))
            if Path(path).is_absolute(): values[name]=Path(path)
    for name,default in names.items(): result['xdg-' + name.lower()] = values.get(name,home/default)
    return result


def resolve_location(loc):
    loc = location(loc)
    root = Path('/') if loc['base']=='absolute' else _locations()[loc['base']]
    return (root/loc.get('path','')).absolute()


def _native_path(token):
    token = token.split(':',1)[0]
    if token in ('host','host-root'): return Path('/')
    if token == 'home': return Path.home()
    if token.startswith('~/'): return Path.home()/token[2:]
    if token.startswith('/'):
        return Path(token)
    base,_,relative = token.partition('/')
    if base in _locations(): return _locations()[base]/relative
    return None


def native_filesystems(snapshot):
    text = snapshot['policy'].get('Context',{}).get('filesystems','')
    # Escaped separators need full GKeyFile parsing; refuse rather than guessing.
    if '\\' in text:
        raise r.ReleaseError('escaped native filesystem policy needs unsupported parsing; nothing changed')
    return [entry for entry in text.split(';') if entry]


def path_access(snapshot, path):
    path = Path(path).resolve()
    matches = []
    for token in native_filesystems(snapshot):
        deny = token.startswith('!');value=token.lstrip('!');root=_native_path(value)
        if root is None:
            if value.startswith(('host-', 'xdg-')):
                raise r.ReleaseError('unsupported broad native filesystem scope; nothing changed')
            continue
        root = root.resolve()
        if path == root or root in path.parents:
            matches.append((len(root.parts), not deny, 'read-only' if value.endswith(':ro') else 'read-write'))
    if not matches:return None
    matches.sort(key=lambda item: (item[0], not item[1]))
    _,allowed,access = matches[-1]
    return access if allowed else None


def overlapping_native_grants(snapshot, path):
    """Include descendant grants; checking only a directory misses child holes."""
    path = Path(path).resolve()
    found = []
    for token in native_filesystems(snapshot):
        if token.startswith('!'):continue
        root = _native_path(token)
        if root is not None and (root.resolve()==path or root.resolve() in path.parents or path in root.resolve().parents):
            if path_access(snapshot,root if path in root.resolve().parents else path):found.append(token)
    return found


def inspect(app, kind):
    record, release, root = installed(app, kind)
    plan = release['entry']['plan']
    if not plan.get('recipe') or plan['recipe'].get('schemaVersion')!='cage.app/v1':
        raise r.ReleaseError('permissions commands require a managed v1 recipe')
    local = local_bindings(app,kind)
    capabilities = compile_capabilities(plan['recipe'],kind,**applicable_inputs(plan['recipe'],local))
    result = {'applicationId':app,'format':kind,'capabilities':capabilities,'activeReleaseSha256':release['digest'],
              'nativeOverridesWritten':False}
    result['inactiveRetainedInputs']={key:sorted(set(local.get(key,{}))-set(applicable_inputs(plan['recipe'],local)[key])) for key in ('decisions','bindings')}
    if kind == 'flatpak': result['native'] = native_snapshot(release)
    if kind == 'flatpak':
        result['effectiveFilesystemUnion']=native_filesystems(result['native'])
        result['enforcementAuthority']='native-effective-policy; requested scope is reported separately'
    return result


def bind(app, kind, request_id, new_location):
    record, release, ledger_root = installed(app, kind)
    recipe = release['entry']['plan'].get('recipe',{})
    local = local_bindings(app,kind)
    before = compile_capabilities(recipe,kind,**applicable_inputs(recipe,local))
    request = next((x['resolved'] for x in before['requests'] if x['id']==request_id),None)
    if not request or request['kind']!='filesystem':raise r.ReleaseError('binding requires an existing filesystem request')
    new_location = location(new_location)
    next_bindings = {**local.get('bindings',{}),request_id:new_location}
    inputs=applicable_inputs(recipe,{**local,'bindings':next_bindings})
    compile_capabilities(recipe,kind,**inputs)
    from artifact.capability_runtime import resolve_files
    resolve_files(compile_capabilities(recipe,kind,**inputs),app,ledger_root)
    old_path,new_path = resolve_location(request['location']),resolve_location(new_location)
    from artifact.capability_runtime import overlaps
    after=compile_capabilities(recipe,kind,**inputs)
    independent=[item['id'] for item in after['requests'] if item['id']!=request_id and item['grant']
                 and item['grant']['kind']=='filesystem' and overlaps(resolve_location(item['resolved']['location']),old_path)]
    if independent and old_path.resolve()!=new_path.resolve():
        return {'adopted':False,'availability':'conflict','nativeOverridesWritten':False,'independentRequests':independent,
                'reason':'Other requests still grant the old scope; exact replacement would revoke independent access. Reconcile the recipe first.'}
    expected = request['access']
    observed = None
    def approved(snapshot):
        return path_access(snapshot,new_path)==expected and (old_path.resolve()==new_path.resolve() or not overlapping_native_grants(snapshot,old_path))
    if kind=='flatpak':
        observed = native_snapshot(release)
        if not approved(observed):
            def spec(loc):
                return loc['path'] if loc['base']=='absolute' else ('~' if loc['base']=='home' else loc['base']) + ('/' + loc['path'] if loc.get('path') else '')
            return {'adopted':False,'availability':'host-setup-required','nativeOverridesWritten':False,
                    'nativeCommand':['flatpak','override','--user','--nofilesystem='+spec(request['location']),
                                     '--filesystem='+spec(new_location)+(':ro' if expected=='read-only' else ':create' if request['create'] else ':rw'),app],
                    'reason':'Apply/review this native delta in Flatseal or the native CLI; rerun bind to verify/adopt.',
                    'observed':observed}
    path = bindings_path(app,kind)
    from artifact import managed_launch, release_install
    state = managed_launch.state_root(record,release)
    with lifecycle_lock(release_install.installation(ledger_root,app,kind)), lifecycle_lock(state), lifecycle_lock(authority.authority_folder(app)):
        # Check both local and authoritative native snapshots again under our lock.
        if installed(app,kind)[1]['digest']!=release['digest']:raise r.ReleaseError('active release changed during binding; reinspect')
        if local_bindings(app,kind) != local:raise r.ReleaseError('local bindings changed; reinspect')
        if kind=='flatpak' and native_snapshot(release)['digest'] != observed['digest']:
            raise r.ReleaseError('native permissions changed during adoption; nothing restored or overwritten')
        result = {'schemaVersion':'cage.local-capability-bindings/v1','applicationId':app,
                  **local, 'bindings':next_bindings,'decisions':local.get('decisions',{}),
                  'nativeSnapshotDigest':observed['digest'] if observed else None,
                  'releaseDigest':release['digest']}
        result.pop('conflicted',None)
        _write_state_record(path,result)
        if kind=='flatpak' and native_snapshot(release)['digest'] != observed['digest']:
            # Retain the receipt as a conflicted decision; never undo native edits.
            result['conflicted']=True;_write_state_record(path,result)
            raise r.ReleaseError('native permissions changed after adoption; reconcile before managed launch')
    return {'adopted':True,'applicationId':app,'format':kind,'binding':{request_id:new_location},'nativeOverridesWritten':False}
