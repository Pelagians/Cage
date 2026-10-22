"""Signed, static Cage releases. No implicit key discovery or update service.

Only verified metadata chooses downloads. Cached release bytes remain immutable;
format-specific deployment and prefix transactions live in release_install.py.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, urlopen

from runtime.desktop_launch import (DesktopError, copy_file, digest_json,
                                    lifecycle_lock, plan_identity, validate_update_policy)

SCHEMA = 'cage.release/v1'
LIMIT = 4 * 1024**2
RESERVE = 128 * 1024**2
FORMATS = ('flatpak', 'appimage', 'oci')


class ReleaseError(DesktopError):
    pass


def crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization
        return Ed25519PrivateKey, Ed25519PublicKey, serialization
    except ImportError as exc:
        raise ReleaseError('trusted releases require the optional dependency: pip install "cage[releases]"') from exc


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode()


def parse(data):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:raise ReleaseError('duplicate JSON key')
            result[k] = v
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except ReleaseError:
        raise
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ReleaseError('invalid release JSON') from exc


def hash_file(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f, 'sha256').hexdigest()


def qualified_identity(proof, identity):
    records=proof.get('sessions',[]) or proof.get('generations',{}).get('generations',[])
    return any(item.get('identity')==identity for item in records)


def oci_image_id(value):
    if isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value):return 'sha256:'+value
    if isinstance(value,str) and re.fullmatch('sha256:[a-f0-9]{64}',value):return value
    raise ReleaseError('container engine/evidence returned an invalid image identity')


def qualified_hashes(proof, kind):
    values=proof.get('sourceImageIds' if kind=='oci' else 'sourceArtifactHashes',{})
    if not isinstance(values,dict):raise ReleaseError('invalid package/image qualification bindings')
    if kind=='oci':return {oci_image_id(value) for value in values.values()}
    if any(not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value) for value in values.values()):
        raise ReleaseError('invalid qualified package hash')
    return set(values.values())


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():raise ReleaseError('expected a regular file: ' + str(path))
    return path


def directory(path):
    path = Path(path).absolute()
    # Refuse links inside the selected private cache, including its root.
    if path.is_symlink():raise ReleaseError('linked release directory: ' + str(path))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def filename(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,220}', name) or '..' in name:
        raise ReleaseError('release assets require plain filenames')
    return name


def public_key(path):
    _, cls, serialization = crypto()
    try:
        key = serialization.load_pem_public_key(small(path, 64*1024))
    except (ValueError, TypeError) as exc:raise ReleaseError('invalid publisher public key') from exc
    if not isinstance(key, cls):raise ReleaseError('publisher key must be Ed25519')
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, hashlib.sha256(raw).hexdigest()


def generate_key(private, public):
    cls, _, serialization = crypto()
    private, public = Path(private), Path(public)
    if private.exists() or private.is_symlink() or public.exists() or public.is_symlink():
        raise ReleaseError('key output already exists; no keys replaced')
    key = cls.generate()
    data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    with os.fdopen(os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:f.write(data)
    with public.open('xb') as f:f.write(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return {'publicKeySha256': public_key(public)[1], 'privateKey': str(private), 'publicKey': str(public)}


def signing_key(private):
    cls, _, serialization = crypto()
    private = regular(private)
    if private.stat().st_mode & 0o077:raise ReleaseError('publisher private key must have mode 0600 or stricter')
    try:key = serialization.load_pem_private_key(small(private, 64*1024), password=None)
    except (ValueError, TypeError) as exc:raise ReleaseError('invalid unencrypted publisher private key') from exc
    if not isinstance(key, cls):raise ReleaseError('publisher key must be Ed25519')
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, hashlib.sha256(raw).hexdigest()


def verify_manifest(data, signature, key_path):
    if len(data) > LIMIT or len(signature) != 64:raise ReleaseError('release metadata/signature exceeds its bounds')
    key, fingerprint = public_key(key_path)
    from cryptography.exceptions import InvalidSignature
    try:key.verify(signature, b'Cage trusted release v1\0' + data)
    except InvalidSignature as exc:raise ReleaseError('invalid publisher signature; no deployment changed') from exc
    manifest = parse(data)
    try:
        if manifest['schemaVersion'] != SCHEMA or manifest['publisherKeySha256'] != fingerprint:raise ValueError()
        if set(manifest)!={'schemaVersion','publisherKeySha256','sequence','sourceRevision','application','artifacts'}:raise ValueError()
        if type(manifest['sequence']) is not int or not 0 < manifest['sequence'] < 2**53:raise ValueError()
        if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', manifest['sourceRevision']):raise ValueError()
        app = manifest['application']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{2,180}', app['id']):raise ValueError()
        if not all(isinstance(app[k], str) and app[k] and len(app[k]) < 200 for k in ('name','version')):raise ValueError()
        entries = manifest['artifacts']
        if not isinstance(entries, list) or not 1 <= len(entries) <= 6:raise ValueError()
        targets = set()
        for entry in entries:
            kind, arch = entry['format'], entry['architecture']
            if kind not in FORMATS or arch not in ('x86_64','aarch64') or (kind,arch) in targets:raise ValueError()
            targets.add((kind,arch))
            expected={'format','architecture','plan','identity','recipeDigest','hostPageSizes','testedPageSizes','package','evidence'}
            expected|={'imageId'} if kind=='oci' else {'receipt','flatpakCommit'} if kind=='flatpak' else {'receipt'}
            if set(entry)!=expected:raise ValueError()
            plan = entry['plan']
            if plan['desktop']['id'] != app['id'] or plan['application'] != {'name':app['name'],'version':app['version']}:raise ValueError()
            if plan.get('state',{}).get('managerVersion') != 1 or entry['identity'] != plan_identity(plan):raise ValueError()
            validate_update_policy(plan['desktop']['updates'])
            if not re.fullmatch('[a-f0-9]{64}',entry['recipeDigest']):raise ValueError()
            if not isinstance(entry['hostPageSizes'], list) or not entry['hostPageSizes'] or any(type(n) is not int or n not in (4096,16384,65536) for n in entry['hostPageSizes']):raise ValueError()
            supported=plan['target'].get('translation',{}).get('hostPageSizes',[]) if arch=='aarch64' else [4096]
            if any(n not in supported for n in entry['hostPageSizes']):raise ValueError()
            if kind != 'oci' and (plan.get('format')!=kind or plan['target']['architecture']!=arch):raise ValueError()
            if kind != 'oci' and entry['recipeDigest']!=plan['sourceManifestDigest']:raise ValueError()
            if kind=='appimage' and plan['state'].get('namespace')!='cage/appimage':raise ValueError()
            if kind == 'flatpak' and not re.fullmatch('[a-f0-9]{64}',entry['flatpakCommit']):raise ValueError()
            if not isinstance(entry['testedPageSizes'],list) or not entry['testedPageSizes'] or any(p not in entry['hostPageSizes'] for p in entry['testedPageSizes']):raise ValueError()
            for asset in (entry['package'],entry['evidence'],*([entry['receipt']] if kind!='oci' else [])):
                filename(asset['name'])
                if set(asset)!={'name','size','sha256'}:raise ValueError()
                if not re.fullmatch('[a-f0-9]{64}', asset['sha256']) or type(asset['size']) is not int or not 0 < asset['size'] <= 32*1024**3:raise ValueError()
                if asset is not entry['package'] and asset['size']>LIMIT:raise ValueError()
            if kind == 'oci' and not re.fullmatch('sha256:[a-f0-9]{64}',entry['imageId']):raise ValueError()
    except (KeyError, TypeError, ValueError, DesktopError) as exc:
        raise ReleaseError('unsupported or inconsistent signed release metadata') from exc
    return manifest


def _origin(source):
    uri=urlsplit(str(source))
    if uri.scheme:
        if uri.scheme not in ('https','http') or (uri.scheme=='http' and uri.hostname not in ('127.0.0.1','localhost','::1')):
            raise ReleaseError('remote releases require HTTPS (HTTP is limited to loopback qualification)')
        if uri.username or uri.password or uri.query or uri.fragment:raise ReleaseError('release URLs must not contain credentials, queries or fragments')
        return uri
    return None


def read_source(source, limit):
    uri = _origin(source)
    if uri:
        request = Request(str(source), headers={'User-Agent':'Cage-trusted-releases/1','Accept-Encoding':'identity'})
        response = urlopen(request, timeout=60)
        final = _origin(response.geturl())
        if not final or (final.scheme,final.netloc)!=(uri.scheme,uri.netloc):
            response.close();raise ReleaseError('cross-origin release redirect refused')
        return response
    return regular(source).open('rb')


def small(source, limit=LIMIT):
    with read_source(source,limit) as f:data=f.read(limit+1)
    if len(data)>limit:raise ReleaseError('release metadata exceeds its size limit')
    return data


def sibling(source, name):
    filename(name)
    return urljoin(str(source),name) if _origin(source) else str(Path(source).parent/name)


def asset_valid(path, asset):
    return regular(path).stat().st_size == asset['size'] and hash_file(path) == asset['sha256']


def _fetch_asset(source, folder, asset):
    path=folder/filename(asset['name'])
    if path.exists() or path.is_symlink():
        if not asset_valid(path,asset):raise ReleaseError('retained release asset changed: '+str(path))
        return path
    if shutil.disk_usage(folder).free < asset['size'] + RESERVE:raise ReleaseError('insufficient space for release download plus reserve; no deployment changed')
    partial=folder/(asset['name']+'.partial')
    # Only an unverified, private partial download may be restarted. Never
    # truncate a retained asset or any file in an application state directory.
    fd=os.open(partial,os.O_CREAT|os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as output, read_source(source,asset['size']) as response:
        total=0; digest=hashlib.sha256()
        while chunk:=response.read(min(1024**2,asset['size']-total+1)):
            total+=len(chunk)
            if total>asset['size']:raise ReleaseError('release asset exceeds signed size')
            output.write(chunk);digest.update(chunk)
        output.flush();os.fsync(output.fileno())
    if total!=asset['size'] or digest.hexdigest()!=asset['sha256']:raise ReleaseError('release asset hash/size mismatch; partial retained')
    partial.replace(path)
    return path


def verify_evidence(entry, proof):
    kind=entry['format'];arch=entry['architecture']
    if (proof.get('status')!='passed' or proof.get('architecture')!=arch or proof.get('format')!=kind
        or not qualified_identity(proof,entry['identity'])
        or not all(proof.get(k) is True for k in ('settingsPreserved','documentsPreserved','rollback'))):
        raise ReleaseError('release lacks matching successful application qualification evidence')
    if (entry['imageId'] if kind=='oci' else entry['package']['sha256']) not in qualified_hashes(proof,kind):
        raise ReleaseError('qualification does not bind the exact package/image bytes')
    if proof.get('pageSize') not in entry['testedPageSizes']:raise ReleaseError('qualification page size differs from signed evidence')


def verify_receipt(entry, receipt):
    kind=entry['format']
    if kind!='oci':
        if receipt.get('plan')!=entry['plan'] or receipt.get('sha256')!=entry['package']['sha256']:raise ReleaseError('signed export receipt and package/plan differ')
        if entry['receipt']['name']!=entry['package']['name']+'.json':raise ReleaseError('export receipt must be adjacent to its package')
        if kind=='flatpak' and receipt.get('commit')!=entry['flatpakCommit']:raise ReleaseError('Flatpak commit differs from signed receipt')


def cached_release(folder, key, kind, *, arch=None, host=True):
    folder=Path(folder)
    if folder.is_symlink() or folder.parent.is_symlink():raise ReleaseError('linked retained release directory')
    data=small(folder/'release.json');sig=small(folder/'release.json.sig',64)
    manifest=verify_manifest(data,sig,key)
    if folder.name != hashlib.sha256(data).hexdigest():raise ReleaseError('cached release identity changed')
    arch=arch or {'amd64':'x86_64','arm64':'aarch64'}.get(platform.machine(),platform.machine())
    found=[a for a in manifest['artifacts'] if a['format']==kind and a['architecture']==arch]
    if len(found)!=1:raise ReleaseError('release has no artifact for this format and host architecture')
    entry=found[0]
    if host and os.sysconf('SC_PAGE_SIZE') not in entry['hostPageSizes']:raise ReleaseError('host page size unsupported by this release runtime')
    for asset in (entry['package'],entry['evidence'],*([entry['receipt']] if kind!='oci' else [])):
        if not asset_valid(folder/asset['name'],asset):raise ReleaseError('retained release asset changed')
    verify_evidence(entry,parse(small(folder/entry['evidence']['name'])))
    if kind!='oci':verify_receipt(entry,parse(small(folder/entry['receipt']['name'])))
    if kind=='appimage':regular(folder/entry['package']['name']).chmod(0o755)
    return {'manifest':manifest,'entry':entry,'directory':str(folder),'digest':folder.name}


def cache_root(path=None):
    return directory(path or Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'cage/releases')


def fetch_release(source, key, kind, *, cache=None, arch=None, preflight=None):
    root=cache_root(cache)
    data=small(source);sig=small(str(source)+'.sig',64)
    manifest=verify_manifest(data,sig,key)
    arch=arch or {'amd64':'x86_64','arm64':'aarch64'}.get(platform.machine(),platform.machine())
    found=[a for a in manifest['artifacts'] if a['format']==kind and a['architecture']==arch]
    if len(found)!=1:raise ReleaseError('release has no artifact for this format and host architecture')
    entry=found[0]
    if os.sysconf('SC_PAGE_SIZE') not in entry['hostPageSizes']:raise ReleaseError('host page size unsupported by release runtime')
    if preflight:preflight(manifest)
    digest=hashlib.sha256(data).hexdigest()
    folder=directory(directory(root/'releases')/digest)
    with lifecycle_lock(folder):
        for name,value in (('release.json',data),('release.json.sig',sig)):
            target=folder/name
            if target.exists() or target.is_symlink():
                if regular(target).read_bytes()!=value:raise ReleaseError('retained signed metadata changed')
            else:
                with target.open('xb') as f:f.write(value);f.flush();os.fsync(f.fileno())
        for asset in (entry['evidence'],*([entry['receipt']] if kind!='oci' else [])):
            _fetch_asset(sibling(source,asset['name']),folder,asset)
        verify_evidence(entry,parse(small(folder/entry['evidence']['name'])))
        if kind!='oci':verify_receipt(entry,parse(small(folder/entry['receipt']['name'])))
        _fetch_asset(sibling(source,entry['package']['name']),folder,entry['package'])
    return cached_release(folder,key,kind,arch=arch)


def command(args, **kwargs):
    result=subprocess.run(args,check=False,**kwargs)
    if result.returncode:
        detail=getattr(result,'stderr',None) or ''
        if isinstance(detail,bytes):detail=detail.decode(errors='replace')
        raise ReleaseError('release command failed: '+str(args[:3])+' '+detail[-2000:])
    return result


def oci_metadata(image, engine):
    record=json.loads(command([engine,'image','inspect',image],capture_output=True,text=True).stdout)[0]
    image_id=oci_image_id(record['Id'])
    if record.get('Config',{}).get('Labels',{}).get('io.cage.graphics')!='desktop':raise ReleaseError('trusted OCI desktop releases require a managed desktop image')
    arch={'amd64':'x86_64','arm64':'aarch64'}.get(record.get('Architecture'))
    cid=command([engine,'create','--network=none',image_id],capture_output=True,text=True).stdout.strip()
    try:
        with tempfile.TemporaryDirectory(prefix='cage-release-metadata-') as temp:
            def read(path):
                destination=Path(temp)/'record.json'
                command([engine,'cp',cid+':'+path,str(destination)],capture_output=True)
                data=small(destination);destination.unlink();return parse(data)
            manifest=read('/opt/cage/bundle/manifest.cage.json')
            native=manifest['runtime']['provider']=='wine-arm64ec'
            plan=read('/opt/cage/bundle/metadata/native-launch.json' if native else '/opt/cage-lifecycle/plan.json')
    finally:command([engine,'rm',cid],capture_output=True)
    return plan,arch,image_id,digest_json(manifest)


def create_release(spec_path, private, output, *, engine='podman'):
    spec_path=Path(spec_path).absolute();spec=parse(small(spec_path));output=Path(output).absolute()
    if output.exists() or output.is_symlink() or Path(str(output)+'.sig').exists():raise ReleaseError('release output already exists')
    directory(output.parent)
    key,fingerprint=signing_key(private)
    artifacts=[];app=None
    def stage(source, name=None):
        source=regular(source).absolute();name=filename(name or source.name);destination=output.parent/name
        size=source.stat().st_size;digest=hash_file(source)
        if source!=destination:
            if destination.exists() or destination.is_symlink():
                if hash_file(regular(destination))!=digest:raise ReleaseError('release asset output collision')
            else:copy_file(source,destination)
        if source.stat().st_size!=size or hash_file(source)!=digest or hash_file(regular(destination))!=digest:
            raise ReleaseError('release input changed during staging; no manifest signed')
        return {'name':name,'size':size,'sha256':digest}
    for item in spec['artifacts']:
        kind=item['format'];source=(spec_path.parent/item['path']).absolute()
        if kind=='oci':
            plan,arch,image_id,recipe=oci_metadata(item['image'],engine)
            if source.exists() or source.is_symlink():raise ReleaseError('OCI archive output already exists; never sign an unrelated saved archive')
            partial=Path(str(source)+'.partial')
            if partial.exists() or partial.is_symlink():raise ReleaseError('interrupted OCI producer archive retained; move it aside before retrying')
            command([engine,'save','--format=oci-archive','--output',str(partial),image_id],capture_output=True)
            partial.replace(source)
        else:
            receipt=parse(small(str(source)+'.json'));plan=receipt['plan']
            if receipt.get('schemaVersion')!='cage.'+kind+'-export-result/v0' or receipt.get('sha256')!=hash_file(regular(source)) or plan.get('format')!=kind:
                raise ReleaseError('export receipt does not match package')
            arch=plan['target']['architecture'];recipe=plan['sourceManifestDigest']
        application={'id':plan['desktop']['id'],**plan['application']}
        if app is not None and app!=application:raise ReleaseError('release artifacts must describe the same application version')
        app=application
        evidence=(spec_path.parent/item['evidence']).absolute()
        proof=parse(small(evidence))
        if (proof.get('status')!='passed' or proof.get('format')!=kind or proof.get('architecture')!=arch
            or not qualified_identity(proof,plan_identity(plan))
            or not all(proof.get(k) is True for k in ('settingsPreserved','documentsPreserved','rollback'))):
            raise ReleaseError('artifact has no matching successful application qualification evidence')
        if (image_id if kind=='oci' else hash_file(source)) not in qualified_hashes(proof,kind):
            raise ReleaseError('qualification does not bind the exact package/image bytes')
        entry={'format':kind,'architecture':arch,'plan':plan,'identity':plan_identity(plan),'recipeDigest':recipe,
               'hostPageSizes':plan['target'].get('translation',{}).get('hostPageSizes',[]) if arch=='aarch64' else [4096],
               'testedPageSizes':[proof['pageSize']], 'package':stage(source),
               'evidence':stage(evidence,'proof-'+hash_file(evidence)+'.json')}
        if kind=='oci':entry['imageId']=image_id
        else:
            entry['receipt']=stage(Path(str(source)+'.json'),entry['package']['name']+'.json')
            if kind=='flatpak':entry['flatpakCommit']=receipt.get('commit')
        artifacts.append(entry)
    manifest={'schemaVersion':SCHEMA,'publisherKeySha256':fingerprint,'sequence':spec['sequence'],
              'sourceRevision':spec['sourceRevision'],'application':app,'artifacts':artifacts}
    data=canonical(manifest);signature=key.sign(b'Cage trusted release v1\0'+data)
    # Validate our output through the same schema/signature path without ever
    # writing the publisher's private material to a release or cache.
    with tempfile.TemporaryDirectory() as temp:
        _,_,serialization=crypto();pub=Path(temp)/'public.pem'
        pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        verify_manifest(data,signature,pub)
    with output.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    with Path(str(output)+'.sig').open('xb') as f:f.write(signature);f.flush();os.fsync(f.fileno())
    return {'release':str(output),'sha256':hashlib.sha256(data).hexdigest(),'publisherKeySha256':fingerprint}
