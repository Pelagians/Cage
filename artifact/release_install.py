"""Trusted release delivery around Cage's existing package/state transactions.

The signed history authorizes artifacts. The application's durable generation
record chooses the active package; this ledger never rewinds a Wine prefix.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from artifact import releases as r
from runtime.desktop_launch import (lifecycle_lock, _write_state_record,
                                    _read_generations, _generation, validate_runtime_update,
                                    rollback_repair_source, DesktopError)


def installation(root, app, kind):
    if kind not in r.FORMATS or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{2,180}',app):raise r.ReleaseError('invalid installed release identity')
    return r.directory(r.directory(r.directory(root/'installed')/app)/kind)


def _read(folder):
    path=folder/'installation.json'
    if not path.exists() and not path.is_symlink():return None
    value=r.parse(r.small(path))
    if value.get('schemaVersion')!='cage.release-installation/v1':raise r.ReleaseError('unknown installation ledger; all state retained')
    return value


def _save(folder, value):
    _write_state_record(folder/'installation.json',value)


def retained(root, digest, key, kind):
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise r.ReleaseError('invalid retained release identity')
    return r.cached_release(root/'releases'/digest,key,kind)


def package(release):
    return str(Path(release['directory'])/release['entry']['package']['name'])


def _state(record, release):
    entry=release['entry'];kind=entry['format'];app=release['manifest']['application']['id']
    if kind=='flatpak':
        from artifact.updates import _state as flatpak_state
        info=flatpak_state({'plan':entry['plan']},dict(os.environ));return info.get('state')
    if kind=='appimage':
        data=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))
        return _read_generations(data/'cage/appimage'/app)
    return _read_generations(Path(record['stateDirectory'])/app)


def _selected(root, record, key, kind, *, previous=False):
    baseline=retained(root,record['baseline'],key,kind)
    history=[retained(root,digest,key,kind) for digest in record['releases']]
    if kind=='flatpak':
        commit=_flatpak_commit(baseline)
        if commit not in {rel['entry']['flatpakCommit'] for rel in history}:
            raise r.ReleaseError('installed Flatpak commit is not in retained signed history; no application code executed')
    state=_state(record,baseline)
    if state is None:
        if previous:raise r.ReleaseError('launch the installed baseline before rollback')
        return baseline
    name=state.get('previous') if previous else state['active']
    if not name:raise r.ReleaseError('no previous generation available')
    active=_generation(state,name)['identity'];matches=[]
    for release in history:
        if release['entry']['identity']==active:matches.append(release)
    if len(matches)!=1:raise r.ReleaseError('active generation has no unique retained signed release; retain all packages and state')
    return matches[0]


def _flatpak_commit(release):
    from artifact.updates import _ref
    return r.command(['flatpak','info','--user','--show-commit',_ref({'plan':release['entry']['plan']})],capture_output=True,text=True).stdout.strip()


def _check_deployment(record, selected):
    if selected['entry']['format']=='flatpak' and _flatpak_commit(selected)!=selected['entry']['flatpakCommit']:
        raise r.ReleaseError('Flatpak deployment and committed generation differ; recover before launching')


def _check_publisher(record, manifest):
    if record['publisherKeySha256']!=manifest['publisherKeySha256']:raise r.ReleaseError('publisher key differs from installed trust pin; no deployment changed')


def _container_load(release, engine):
    r.command([engine,'load','--input',package(release)],capture_output=True,text=True)
    plan,arch,image_id,recipe=r.oci_metadata(release['entry']['imageId'],engine)
    entry=release['entry']
    if (plan!=entry['plan'] or arch!=entry['architecture'] or image_id!=entry['imageId'] or recipe!=entry['recipeDigest']):
        raise r.ReleaseError('loaded container does not match signed release identity')


def _container_args(record, release, files, action=None):
    # Match the already qualified direct desktop OCI workflow. No host network,
    # home directory, daemon socket or arbitrary mount from release metadata.
    env=os.environ;exports=Path(record['exportsDirectory']).resolve();mapped=[]
    for name in files:
        path=Path(name).resolve()
        if not path.is_relative_to(exports):raise r.ReleaseError('container documents must be inside the explicitly selected exports directory')
        mapped.append('/exports/'+path.relative_to(exports).as_posix())
    args=[record['engine'],'run','--rm','--pull=never','--userns=keep-id','--user','0:0','--network=none',
          '--hostname',os.uname().nodename,'--security-opt','label=disable',
          '-e','PUID='+str(os.getuid()),'-e','PGID='+str(os.getgid()),
          '-v',record['stateDirectory']+':/var/lib/cage/state','-v',str(exports)+':/exports']
    if env.get('DISPLAY'):
        args+=['-e','DISPLAY','-v','/tmp/.X11-unix:/tmp/.X11-unix:ro']
        if env.get('XAUTHORITY'):args+=['-e','XAUTHORITY=/tmp/cage-xauthority','-v',str(Path(env['XAUTHORITY']).absolute())+':/tmp/cage-xauthority:ro']
    args+=[release['entry']['imageId']]
    if action:args+=['--cage-'+action]
    return args+['--',*mapped]


def _install(record, release):
    entry=release['entry'];kind=entry['format']
    if kind=='flatpak':
        from artifact.updates import _command, _ref, identity
        env=dict(os.environ);target={'plan':entry['plan']};ref=_ref(target)
        existing=subprocess.run(['flatpak','info','--user',ref],env=env,capture_output=True,text=True)
        if existing.returncode==0:
            if _flatpak_commit(release)!=entry['flatpakCommit']:raise r.ReleaseError('installed Flatpak commit differs from signed baseline')
            plan=json.loads(_command(['run','--user','--command=cat',ref,'/app/share/cage/'+entry['plan']['desktop']['id']+'/desktop.json'],env))
            if identity(plan)!=entry['identity']:raise r.ReleaseError('an existing Flatpak differs from this baseline; use its supported migration/update workflow')
        else:
            # Native Flatpak handles platform installation through remotes the
            # user has already configured. Never add a remote or delete data.
            _command(['install','--user','--noninteractive','--assumeyes','--no-related','--bundle',package(release)],env,capture=False)
            if _flatpak_commit(release)!=entry['flatpakCommit']:raise r.ReleaseError('installed Flatpak commit differs from signed package')
    elif kind=='appimage':
        data=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))
        installed=data/'cage/appimages'/entry['plan']['desktop']['id']
        if installed.exists() or installed.is_symlink():
            receipt=r.parse(r.small(r.regular(installed/'installation.json')))
            if (receipt.get('package')!=entry['package']['sha256'] or
                r.hash_file(r.regular(installed/'application.AppImage'))!=entry['package']['sha256']):
                raise r.ReleaseError('existing AppImage installation differs from signed baseline; use supported migration/update')
        else:r.command([package(release),'--cage-install'],capture_output=True,text=True)
    else:
        _container_load(release,record['engine'])
        root=Path(record['stateDirectory']);app=release['manifest']['application']['id']
        if (root/'prefix').exists() or (root/'prefix').is_symlink():raise r.ReleaseError('untracked legacy container state retained; qualify its explicit migration first')
        state=_read_generations(root/app)
        if state and _generation(state,state['active'])['identity']!=entry['identity']:raise r.ReleaseError('container state differs from signed baseline')


def _launch(record, release, files, action=None, previous=None, folder=None):
    kind=release['entry']['format']
    if kind=='flatpak':
        from artifact.updates import update_flatpak, _ref
        if action:return update_flatpak(package(release),package(previous),rollback=action=='rollback',repair=action=='rollback-repair',files=files,cache=folder/'flatpak-transaction')
        return r.command(['flatpak','run','--user',_ref({'plan':release['entry']['plan']}),'--',*map(str,files)])
    if kind=='appimage':
        return r.command([package(release),*(['--cage-'+action] if action else []),'--',*map(str,files)])
    return r.command(_container_args(record,release,files,action))


def deploy(source, key, kind, *, action='install', cache=None, files=(), engine='podman', state_dir=None, exports_dir=None):
    root=r.cache_root(cache)
    def preflight(manifest):
        found=_read(installation(root,manifest['application']['id'],kind))
        if found:
            _check_publisher(found,manifest)
            if found.get('pending'):raise r.ReleaseError('unfinished trusted deployment; recover before proceeding')
            if action=='install':raise r.ReleaseError('trusted installation already recorded; use update or run')
            if manifest['sequence']<=found['highWater']:
                known_repair = action=='rollback-repair' and any(retained(root,d,key,kind)['manifest']==manifest for d in found['releases'])
                if not known_repair:raise r.ReleaseError('release sequence is stale or already accepted; use explicit rollback')
        elif action!='install':raise r.ReleaseError('no trusted baseline installed; install the matching baseline first')
    release=r.fetch_release(source,key,kind,cache=root,preflight=preflight)
    manifest=release['manifest'];app=manifest['application']['id'];folder=installation(root,app,kind)
    with lifecycle_lock(folder):
        record=_read(folder)
        if record and record.get('pending'):raise r.ReleaseError('unfinished trusted deployment; run cage release recover '+app+' --format '+kind)
        if action=='install':
            if record:raise r.ReleaseError('trusted installation already recorded; use update or run')
            record={'schemaVersion':'cage.release-installation/v1','publisherKeySha256':manifest['publisherKeySha256'],
                    'applicationId':app,'format':kind,'highWater':manifest['sequence'],'releases':[release['digest']],
                    'baseline':release['digest']}
            if kind=='oci':
                if engine!='podman':raise r.ReleaseError('managed OCI release launches currently require Podman keep-id semantics')
                state=r.directory(Path(state_dir).absolute() if state_dir else folder/'state')
                exports=r.directory(Path(exports_dir).absolute() if exports_dir else folder/'documents')
                if ':' in str(state) or ':' in str(exports) or state==exports or state.is_relative_to(exports) or exports.is_relative_to(state):
                    raise r.ReleaseError('container state and document directories must be separate, disjoint mount paths')
                if root.is_relative_to(state) or root.is_relative_to(exports):raise r.ReleaseError('container mounts must not expose the trusted release cache')
                record.update(engine=engine,stateDirectory=str(state),exportsDirectory=str(exports))
            record['pending']={'action':'install','target':release['digest']};_save(folder,record)
            _install(record,release)
            existing_state=_state(record,release)
            if existing_state and _generation(existing_state,existing_state['active'])['identity']!=release['entry']['identity']:
                raise r.ReleaseError('existing application state differs from signed baseline; no prefix imported or reset')
            record.pop('pending');_save(folder,record)
            if files:_launch(record,release,files)
        elif action in {'update','rollback-repair'}:
            if not record:raise r.ReleaseError('no trusted baseline installed; install the matching baseline first')
            _check_publisher(record,manifest)
            known_repair = action=='rollback-repair' and release['digest'] in record['releases']
            if manifest['sequence']<=record['highWater'] and not known_repair:raise r.ReleaseError('release sequence is stale or already accepted; use explicit rollback for retained history')
            previous=_selected(root,record,key,kind)
            _check_deployment(record,previous)
            if _state(record,previous) is None:raise r.ReleaseError('launch the installed baseline once before updating')
            try:
                source_release = previous
                if action=='rollback-repair':
                    source, _ = rollback_repair_source(_state(record,previous),release['entry']['identity'],release['entry']['plan'])
                    history = [retained(root,d,key,kind) for d in record['releases']]
                    matches = [rel for rel in history if rel['entry']['identity']==source['identity']]
                    if len(matches)!=1:raise DesktopError('repair source has no unique retained signed release')
                    source_release = matches[0]
                validate_runtime_update(source_release['entry']['plan'], release['entry']['plan'], repair=action=='rollback-repair')
            except DesktopError as exc:
                raise r.ReleaseError('runtime or migration qualification refused: ' + str(exc)) from exc
            if manifest['application']['name']!=previous['manifest']['application']['name']:raise r.ReleaseError('application name changed')
            if not known_repair and any(retained(root,d,key,kind)['entry']['identity']==release['entry']['identity'] for d in record['releases']):
                raise r.ReleaseError('release has no new application generation')
            if state_dir or exports_dir:raise r.ReleaseError('update cannot change installed state/document mount paths')
            # Pin the high-water sequence and retain authorization before user
            # code may commit. A failed trial never re-enables stale releases.
            record['highWater']=max(record['highWater'],manifest['sequence'])
            if not known_repair:record['releases'].append(release['digest'])
            record['pending']={'action':action,'target':release['digest']};_save(folder,record)
            if kind=='oci':_container_load(release,record['engine'])
            _launch(record,release,files,action=action,previous=previous,folder=folder)
            selected=_selected(root,record,key,kind)
            if selected['digest']!=release['digest']:raise r.ReleaseError('trial did not activate requested signed release; recover the transaction')
            record.pop('pending');_save(folder,record)
        else:raise r.ReleaseError('unknown trusted deployment action')
    return {'installed':action=='install','updated':action=='update','repairedRollback':action=='rollback-repair','applicationId':app,'format':kind,
            'releaseSha256':release['digest'],'publisherKeySha256':record['publisherKeySha256'],'stateRetained':True}


def operate(app, key, kind, *, action='run', cache=None, files=()):
    root=r.cache_root(cache);folder=installation(root,app,kind)
    with lifecycle_lock(folder):
        record=_read(folder)
        if not record:raise r.ReleaseError('no trusted installation recorded')
        _,fingerprint=r.public_key(key)
        if record['publisherKeySha256']!=fingerprint:raise r.ReleaseError('publisher key differs from installed trust pin')
        if record.get('pending') and action!='recover':raise r.ReleaseError('unfinished trusted deployment; run cage release recover first')
        if action=='recover':
            pending=record.get('pending')
            if pending and pending['action']=='install':
                target=retained(root,pending['target'],key,kind);_install(record,target)
            elif kind=='flatpak' and (folder/'flatpak-transaction/transaction.json').exists():
                from artifact.updates import recover_flatpak
                journal=r.parse(r.small(folder/'flatpak-transaction/transaction.json'))
                history=[retained(root,d,key,kind) for d in record['releases']]
                if _flatpak_commit(history[0]) not in {rel['entry']['flatpakCommit'] for rel in history}:
                    raise r.ReleaseError('installed Flatpak commit is not in signed history; no recovery helper executed')
                authorized={rel['entry']['package']['sha256']:{'sha256':rel['entry']['package']['sha256'],
                            'identity':rel['entry']['identity'],'plan':rel['entry']['plan']} for rel in history}
                for field in ('candidate','previous'):
                    entry=journal[field]
                    if authorized.get(entry['sha256'])!=entry:raise r.ReleaseError('recovery journal refers to an unsigned package/plan; all state retained')
                recover_flatpak(folder/'flatpak-transaction')
            selected=_selected(root,record,key,kind)
            record.pop('pending',None);_save(folder,record)
            return {'recovered':True,'activeReleaseSha256':selected['digest'],'stateRetained':True}
        selected=_selected(root,record,key,kind)
        _check_deployment(record,selected)
        if action=='info':
            return {'applicationId':app,'format':kind,'activeReleaseSha256':selected['digest'],
                    'activeVersion':selected['manifest']['application']['version'],'highWater':record['highWater'],
                    'retainedReleases':record['releases'],'stateRetained':True}
        if action=='rollback':
            previous=selected;selected=_selected(root,record,key,kind,previous=True)
            record['pending']={'action':'rollback','target':selected['digest']};_save(folder,record)
            _launch(record,selected,files,action='rollback',previous=previous,folder=folder)
            if _selected(root,record,key,kind)['digest']!=selected['digest']:raise r.ReleaseError('rollback did not activate the retained signed release')
            record.pop('pending');_save(folder,record)
        elif action=='run':_launch(record,selected,files)
        else:raise r.ReleaseError('unknown trusted release operation')
    return {'success':True,'action':action,'applicationId':app,'activeReleaseSha256':selected['digest'],'stateRetained':True}
