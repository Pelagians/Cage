"""v2 release bindings: exact selection independent of state compatibility.

Reuses the signed release cache and prefix lifecycle. v1 ledgers stay readable
through their original adapter and are never silently reinterpreted.
"""
from __future__ import annotations

import os
from pathlib import Path

from artifact import authority, releases as r, release_install as legacy
from artifact import managed_launch
from artifact.permissions import local_bindings, bindings_path
from core.capabilities import compile_capabilities, require_supported
from runtime.desktop_launch import lifecycle_lock, _write_state_record, _read_generations, _generation, validate_runtime_update

SCHEMA='cage.release-installation/v2'


def selected(root, record, key, kind, *, previous=False):
    field='previousReleaseDigest' if previous else 'activeReleaseDigest'
    digest=record.get(field)
    if not digest:raise r.ReleaseError('no retained previous release')
    if digest not in record['releases']:raise r.ReleaseError('selected release is outside retained authorization')
    release=legacy.retained(root,digest,key,kind)
    binding=record.get('releaseBindings',{}).get(digest)
    expected={'schemaVersion':'cage.release-state-binding/v1','applicationId':record['applicationId'],
              'publisherKeySha256':record['publisherKeySha256'],'identity':release['entry']['identity']}
    if binding!=expected:raise r.ReleaseError('signed release/state binding differs; all state retained')
    if not previous:
        state=legacy._state(record,release)
        if state and _generation(state,state['active'])['identity']!=release['entry']['identity']:
            raise r.ReleaseError('selected release is incompatible with active state; recover without resetting prefixes')
    return release


def _binding(release):
    return {'schemaVersion':'cage.release-state-binding/v1','applicationId':release['manifest']['application']['id'],
            'publisherKeySha256':release['manifest']['publisherKeySha256'],'identity':release['entry']['identity']}


def _accept(release, contract):
    app=release['manifest']['application']['id'];kind=release['entry']['format'];plan=release['entry']['plan']
    capabilities=compile_capabilities(plan['recipe'],kind);require_supported(capabilities)
    local=local_bindings(app,kind)
    if contract != capabilities['contractDigest'] and local.get('acceptedContractDigest')!=capabilities['contractDigest']:
        raise r.ReleaseError('review the release capability plan and pass --accept-permissions '+capabilities['contractDigest'])
    return capabilities['contractDigest']


def _save_acceptance(release, contract):
    app=release['manifest']['application']['id'];kind=release['entry']['format']
    with lifecycle_lock(authority.authority_folder(app)):
        local=local_bindings(app,kind)
        local.update(schemaVersion='cage.local-capability-bindings/v1',applicationId=app,acceptedContractDigest=contract)
        _write_state_record(bindings_path(app,kind),local)


def _occupancy(record, release):
    root=managed_launch.state_root(record,release);kind=release['entry']['format'];app=release['manifest']['application']['id']
    roots=[root]
    if kind=='flatpak':roots.append(Path.home()/'.var/app'/app)
    if kind=='appimage':roots.append(root.parent.parent/'appimages'/app)
    return any(p.exists() or p.is_symlink() for p in roots)


def _verify_adoption(record, release):
    """Only an exact authenticated v2 deployment/state can be explicitly adopted."""
    state=legacy._state(record,release)
    root=managed_launch.state_root(record,release)
    if release['entry']['format']=='appimage':
        previous=root.parent.parent/'appimages'/release['manifest']['application']['id']
        if previous.exists() or previous.is_symlink():
            receipt=r.parse(r.small(r.regular(previous/'installation.json')))
            if receipt.get('package')!=release['entry']['package']['sha256'] or r.hash_file(r.regular(previous/'application.AppImage'))!=release['entry']['package']['sha256']:
                raise r.ReleaseError('untracked AppImage installation differs; retain it and use a fresh ID')
    if _occupancy(record,release) and state is None:
        # Empty state is harmless; unknown native data is never guessed/reset.
        parents=[root]
        if release['entry']['format']=='flatpak':parents.append(Path.home()/'.var/app'/release['manifest']['application']['id'])
        if any(p.is_symlink() or p.exists() and any(p.iterdir()) for p in parents):
            raise r.ReleaseError('untracked retained data lacks a verifiable state record; use a fresh app ID')
    if state and _generation(state,state['active'])['identity']!=release['entry']['identity']:
        raise r.ReleaseError('retained prefix has a different state contract; explicit qualified migration is required')
    if release['entry']['format']=='flatpak' and authority.flatpak_refs(release['manifest']['application']['id']):
        legacy._check_deployment(record,release)
        from artifact.permissions import native_snapshot
        native_snapshot(release)


def _install(record, release, folder, *, restore=False):
    kind=release['entry']['format']
    if kind=='appimage':managed_launch.import_appimage(release,folder)
    elif kind=='oci':legacy._container_load(release,record['engine'])
    else:
        from artifact.updates import _ref
        import subprocess
        installed=subprocess.run(['flatpak','info','--user','--show-commit',_ref({'plan':release['entry']['plan']})],capture_output=True,text=True)
        if installed.returncode or installed.stdout.strip()!=release['entry']['flatpakCommit']:
            r.command(['flatpak','install','--user','--noninteractive','--assumeyes','--no-related',
                       *(['--reinstall','--no-deps'] if restore else ['--or-update']),'--bundle',legacy.package(release)],capture_output=True,text=True)
        legacy._check_deployment(record,release)
        from artifact.permissions import native_snapshot
        native_snapshot(release)


def _safe_state(record, release):
    state=legacy._state(record,release)
    if state and _generation(state,state['active'])['identity']!=release['entry']['identity']:
        raise r.ReleaseError('state compatibility differs; prefix/recovery generations retained')


def deploy(release, key, root, *, action='install', files=(), engine='podman', state_dir=None, exports_dir=None, accepted=None, adopt=False):
    manifest=release['manifest'];app=manifest['application']['id'];kind=release['entry']['format'];folder=legacy.installation(root,app,kind)
    contract=_accept(release,accepted)
    if action not in ('install','update'):raise r.ReleaseError('v2 repaired/state-affecting transitions require separate qualification')
    owner=authority.read_authority(app)
    if owner and owner['publisherKeySha256']!=manifest['publisherKeySha256']:
        raise r.ReleaseError('app ID belongs to another publisher; use a fresh ID')
    record=legacy._read(folder)
    if action=='install':
        if record:raise r.ReleaseError('installation already recorded; legacy records require explicit qualified migration')
        record={'schemaVersion':SCHEMA,'publisherKeySha256':manifest['publisherKeySha256'],'applicationId':app,'format':kind,
                'baseline':release['digest'],'highWater':manifest['sequence'],'releases':[release['digest']],
                'activeReleaseDigest':release['digest'],'previousReleaseDigest':None,'releaseBindings':{release['digest']:_binding(release)}}
        if kind=='oci':
            if engine!='podman':raise r.ReleaseError('v1 OCI requires rootless Podman/crun')
            if exports_dir:raise r.ReleaseError('v1 folders come from recipe grants/bindings; exports-dir is a v0 option')
            state=Path(state_dir).absolute() if state_dir else folder/'state'
            if ',' in str(state) or ':' in str(state) or root.is_relative_to(state.resolve()):raise r.ReleaseError('unsafe state mount scope')
            record.update(engine=engine,stateDirectory=str(state))
        occupied=_occupancy(record,release)
        if occupied or kind=='flatpak' and authority.flatpak_refs(app):
            if not adopt:raise r.ReleaseError('untracked installation/data retained; explicit --adopt-existing verification required')
            _verify_adoption(record,release)
    else:
        if not record or record.get('schemaVersion')!=SCHEMA:raise r.ReleaseError('matching managed v2 installation required')
        legacy._check_publisher(record,manifest)
        if manifest['sequence']<=record['highWater']:raise r.ReleaseError('release sequence already accepted or stale')
        if state_dir or exports_dir:raise r.ReleaseError('update cannot change state mount identity')
        previous=selected(root,record,key,kind)
        validate_runtime_update(previous['entry']['plan'],release['entry']['plan'])
        legacy._check_deployment(record,previous)
    ref=app+'/'+release['entry']['architecture']+'/stable' if kind=='flatpak' else None
    authority.claim(app,key,kind,root,native_ref=ref,adopt=adopt,occupied=_occupancy(record,release))
    with lifecycle_lock(folder):
        current=legacy._read(folder)
        if current and (current.get('pending') or action=='install' or current!=record):
            raise r.ReleaseError('installation changed or awaits recovery; reinspect')
        with lifecycle_lock(managed_launch.state_root(record,release)):
            _safe_state(record,release)
            old_digest=record['activeReleaseDigest']
            record['highWater']=max(record['highWater'],manifest['sequence'])
            if release['digest'] not in record['releases']:record['releases'].append(release['digest'])
            record['releaseBindings'][release['digest']]=_binding(release)
            record['pending']={'action':action,'target':release['digest'],'previous':old_digest,'acceptedContractDigest':contract};legacy._save(folder,record)
            _install(record,release,folder)
            if action=='update':record['previousReleaseDigest']=old_digest
            _save_acceptance(release,contract)
            record['activeReleaseDigest']=release['digest'];record.pop('pending');legacy._save(folder,record)
    if files:managed_launch.launch(record,release,folder,root,files=files)
    from artifact.desktop_integration import install as integrate
    integration=integrate(release,root)
    return {'installed':action=='install','updated':action=='update','applicationId':app,'format':kind,
            'releaseSha256':release['digest'],'stateRetained':True,'nativeOverridesWritten':False,'desktopIntegration':integration}


def operate(app, key, kind, root, *, action='run', files=()):
    owner,registered_root,pinned=authority.registered(app,kind)
    if registered_root.resolve()!=root.resolve() or r.public_key(key)[1]!=owner['publisherKeySha256']:
        raise r.ReleaseError('canonical authority/cache differs; use registered installation')
    folder=legacy.installation(root,app,kind)
    with lifecycle_lock(folder):
        record=legacy._read(folder)
        if record.get('schemaVersion')!=SCHEMA:raise r.ReleaseError('not a v2 installation')
        if record.get('pending') and action!='recover':raise r.ReleaseError('pending deployment; run release recover')
        active=selected(root,record,pinned,kind)
        if action=='info':
            return {'applicationId':app,'activeReleaseSha256':active['digest'],'previousReleaseSha256':record.get('previousReleaseDigest'),
                    'compatibility':active['entry']['identity'],'retainedReleases':record['releases'],'stateRetained':True}
        if action in ('recover','rollback'):
            # Recovery restores the exact committed release, never infers one
            # by searching a non-unique compatibility identity.
            target=active if action=='recover' else selected(root,record,pinned,kind,previous=True)
            if target['entry']['identity']!=active['entry']['identity']:raise r.ReleaseError('unqualified state transition retained')
            with lifecycle_lock(managed_launch.state_root(record,target)):
                _safe_state(record,target)
                if action=='rollback':
                    record['pending']={'action':'rollback','target':target['digest'],'previous':active['digest']};legacy._save(folder,record)
                _install(record,target,folder,restore=True)
                if action=='recover' and record.get('pending',{}).get('action')=='install':
                    _save_acceptance(target,record['pending']['acceptedContractDigest'])
                if action=='rollback':record['previousReleaseDigest']=active['digest']
                record['activeReleaseDigest']=target['digest'];record.pop('pending',None);legacy._save(folder,record)
            return {'success':True,'action':action,'activeReleaseSha256':target['digest'],'stateRetained':True}
        if action!='run':raise r.ReleaseError('unsupported v2 release operation')
        legacy._check_deployment(record,active)
        managed_launch.launch(record,active,folder,root,files=files)
    return {'success':True,'action':'run','activeReleaseSha256':active['digest'],'stateRetained':True}
