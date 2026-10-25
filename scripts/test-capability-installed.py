"""Installed v2 release proof for the disposable runtime-parity application.

Called by test-capability-runtimes.py after actual candidate probes pass. Keys
stay outside uploaded evidence. No installed user application is addressed.
Synthetic device-view evidence never qualifies physical USB or MyHarmony.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

from artifact import authority, permissions, release_install, releases
from artifact.inspection import verify_bundle
from core.manifest import Manifest
from runtime.desktop_launch import copy_file, digest_json, inventory_tree, plan_identity, _read_generations, _write_state_record


def host_identity():
    info = platform.freedesktop_os_release()
    enabled = Path('/sys/module/apparmor/parameters/enabled').read_text().strip() == 'Y'
    restriction = subprocess.check_output(['sysctl', '-n', 'kernel.apparmor_restrict_unprivileged_userns'], text=True).strip()
    if (platform.machine() != 'x86_64' or info['ID'] != 'ubuntu' or info['VERSION_ID'] != '24.04'
            or os.getuid() == 0 or not enabled or restriction != '1' or not os.environ.get('DISPLAY')):
        raise RuntimeError('installed proof requires the qualified native Ubuntu x86_64 X11/AppArmor host')
    tools = {}
    for name in ('podman', 'crun', 'flatpak', 'bwrap'):
        tools[name] = subprocess.check_output([name, '--version'], text=True).strip()
    return {'bootedNative': True, 'architecture': platform.machine(), 'os': info['ID'], 'version': info['VERSION_ID'],
            'desktop': 'x11', 'wine': 'wine-11.0', 'kernel': platform.release(), 'apparmorEnabled': enabled,
            'tools': tools, 'securityPolicy': {'apparmorRestrictUnprivilegedUserns': restriction,
                'namespaceAuthorization': 'scoped test executable; global restriction retained'}}


def policy_variant(h, release, work, store, evidence):
    """Re-export our owned seed with a permission-reason-only recipe revision.

    This is explicitly a fixture producer operation, never a resealing API for
    user bundles. Verify the original and copied seed before and after export.
    """
    kind = release['entry']['format']
    source = work/('oci-bundles' if kind == 'oci' else 'desktop-bundles')/'cage-runtime-parity-1.0.0'
    original = digest_json(inventory_tree(source))
    bundle = work/('policy-'+kind)/'bundle'
    shutil.copytree(source, bundle, symlinks=True, copy_function=copy_file)
    raw = json.loads((bundle/'manifest.cage.json').read_text())
    raw['permissions']['requests'][0]['reason'] += ' (reviewed policy revision)'
    if 'compatibility' in raw:
        raw['compatibility'].pop('schemaVersion', None)
    raw = Manifest.from_dict(raw).to_dict()
    h.write(bundle/'manifest.cage.json', raw)
    receipt = bundle/'metadata/desktop-build.json'
    if receipt.exists():
        value = json.loads(receipt.read_text()); value['manifestDigest'] = digest_json(raw); h.write(receipt, value)
    verification = verify_bundle(bundle); h.write(evidence/'policy-bundle-verification.json', verification)
    if not verification['valid'] or not verification['runnable']:
        raise RuntimeError('policy fixture failed ordinary bundle verification: '+str(verification))
    if kind == 'oci':
        tag = 'localhost/cage-installed-policy:'+release['digest'][:16]
        h.command([sys.executable, '-m', 'cage', 'export', 'oci', bundle, '--engine', 'podman', '--graphics', 'desktop',
                   '--tag', tag, '--context-dir', work/'policy-oci-export'], evidence/'policy-export.log')
        plan, arch, image, recipe = releases.oci_metadata(tag, 'podman')
        entry = {'format': kind, 'architecture': arch, 'plan': plan, 'imageId': image, 'recipeDigest': recipe}
        result = {'entry': entry, 'directory': str(work), 'digest': image.split(':')[-1], 'manifest': release['manifest']}
    else:
        output = work/('policy.flatpak' if kind == 'flatpak' else 'policy.AppImage')
        exported = h.export_flatpak(bundle, output=output, store=store) if kind == 'flatpak' else h.export_appimage(
            bundle, output=output, store=store, cache=h.ROOT/'.cage/appimage-tools')
        h.write(evidence/'policy-export.json', exported)
        entry = {'format': kind, 'architecture': 'x86_64', 'plan': exported['plan'],
                 'package': {'name': output.name, 'sha256': exported['sha256']},
                 'recipeDigest': exported['plan']['sourceManifestDigest']}
        if kind == 'flatpak': entry['flatpakCommit'] = exported['commit']
        result = {'entry': entry, 'directory': str(work), 'digest': exported['sha256'], 'manifest': release['manifest']}
    assert plan_identity(entry['plan']) == plan_identity(release['entry']['plan']), 'policy revision changed state identity'
    assert entry['plan']['capabilities']['contractDigest'] != release['entry']['plan']['capabilities']['contractDigest']
    assert digest_json(inventory_tree(source)) == original, 'original producer bundle changed'
    return result


def proof(h, release, host, observations, evidence):
    kind = release['entry']['format']; plan = release['entry']['plan']
    if (len(observations) != 3 or any(s.get('status') != 'passed' or s.get('settingsPreserved') is not True for s in observations)
            or [s.get('stateCounter') for s in observations] != [4, 5, 6]
            or observations[-1].get('operation') != 'policy-rollback'):
        raise RuntimeError('sign only after actual compatible policy update/rollback observations')
    # Every case points at actual asserted observations of these artifact bytes.
    value = {'status': 'passed', 'format': kind, 'architecture': 'x86_64', 'pageSize': os.sysconf('SC_PAGE_SIZE'),
             'qualificationKind': 'synthetic-probe-compatible-policy-relaunch',
             'settingsPreserved': True, 'documentsPreserved': True, 'rollback': True,
             'sessions': observations,
             'physicalUsbSynchronization': 'unqualified', 'myHarmonyWorkflow': 'not-qualified-by-probe-suite',
             'capabilityQualification': {'contractDigest': plan['capabilities']['contractDigest'],
                 'baseline': 'cage.local-desktop/v1', 'host': host,
                 'cases': {name: {'status': 'passed', 'evidence': 'producer',
                                 'scope': 'hardware-free owned Windows/native-child probe'}
                           for name in ('baseline', 'filesystem', 'network')}}}
    value['capabilityQualification']['cases'].update({name: {'status': 'blocked', 'evidence': 'No controlled physical device or Windows reconnect proof'} for name in ('devices', 'hotplug')})
    identity = release['entry'].get('imageId', release['entry'].get('package', {}).get('sha256'))
    value['sourceImageIds' if kind == 'oci' else 'sourceArtifactHashes'] = {'candidate': identity}
    h.write(evidence, value)
    return value


@contextmanager
def fresh_consumer(work):
    """A separate consumer home/store, retaining every producer state tree."""
    saved = dict(os.environ)
    try:
        home = work/'consumer-home'; home.mkdir(mode=0o700)
        os.environ['HOME'] = str(home)
        for name in ('DATA', 'CONFIG', 'CACHE'):
            folder = home/('xdg-'+name.lower()); folder.mkdir(mode=0o700)
            os.environ['XDG_'+name+'_HOME'] = str(folder)
        os.environ['FLATPAK_USER_DIR'] = str(home/'flatpak')
        yield home
    finally:
        os.environ.clear(); os.environ.update(saved)


def qualify(h, candidates, work, store, paths, port, abstract, device, host_process, shm, evidence):
    if len(candidates) != 1:
        raise RuntimeError('--installed-releases requires --format so each adapter has its own desktop default')
    kind, baseline = next(iter(candidates.items())); app = baseline['manifest']['application']['id']
    evidence.mkdir(parents=True); host = host_identity(); h.write(evidence/'host.json', host)
    private = work/'publisher-private.pem'; key = work/'publisher-public.pem'; releases.generate_key(private, key)
    shutil.copyfile(key, evidence/'publisher-public.pem')
    result = {'schemaVersion': 'cage.installed-release-parity/v1', 'status': 'running', 'format': kind,
              'applicationId': app, 'physicalUsbSynchronization': 'unqualified',
              'myHarmonyWorkflow': 'not-qualified-by-probe-suite', 'sessions': []}
    record = {'stateDirectory': str(work/'oci-state')}
    def candidate_run(release, counter, label):
        value, _, _ = h.run_case(release, record, work, paths, 'shared-all', port, abstract, device, host_process, shm,
                                 evidence/'producer'/label, counter)
        return {**value, 'identity': plan_identity(release['entry']['plan']), 'operation': label, 'exitCode': 0,
                'artifactIdentity': release['entry'].get('imageId', release['entry'].get('package', {}).get('sha256'))}
    try:
        # Reverse the earlier local folder/device decisions, then actually
        # relaunch the original and policy-revised packages before signing.
        sessions = [candidate_run(baseline, 4, 'restore-original-policy')]
        variant = policy_variant(h, baseline, work, store, evidence)
        if kind == 'flatpak': h.install_native(variant, Path(os.environ['FLATPAK_USER_DIR']), evidence/'producer/variant-install')
        sessions.append(candidate_run(variant, 5, 'policy-revision'))
        if kind == 'flatpak': h.install_native(baseline, Path(os.environ['FLATPAK_USER_DIR']), evidence/'producer/baseline-restore')
        sessions.append(candidate_run(baseline, 6, 'policy-rollback'))
        assert (paths['write']/'canary').read_bytes() == b'cage-probe-canary\n'
        signed = []
        for sequence, release in enumerate((baseline, variant), 1):
            folder = work/('signed-'+str(sequence)); folder.mkdir()
            proof_path = folder/'probe-proof.json'; proof(h, release, host, sessions, proof_path)
            artifact = {'format': kind, 'path': str(folder/'probe.oci') if kind == 'oci' else
                        str(Path(release['directory'])/release['entry']['package']['name']), 'evidence': str(proof_path)}
            if kind == 'oci': artifact['image'] = release['entry']['imageId']
            spec_path = folder/'spec.json'
            h.write(spec_path, {'sequence': sequence, 'sourceRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=h.ROOT, text=True).strip(),
                                'artifacts': [artifact]})
            output = folder/'release.json'
            h.command([sys.executable, '-m', 'cage', 'release', 'create', spec_path, '--private-key', private, '--output', output],
                      evidence/('sign-'+str(sequence)+'.log'))
            # Independently authenticate the exact manifest before consumer use.
            manifest = releases.verify_manifest(output.read_bytes(), Path(str(output)+'.sig').read_bytes(), key)
            assert manifest['schemaVersion'] == 'cage.release/v2'
            for source in (output, Path(str(output)+'.sig'), proof_path):
                shutil.copyfile(source, evidence/(str(sequence)+'-'+source.name))
            if kind != 'oci': shutil.copyfile(str(Path(release['directory'])/release['entry']['package']['name'])+'.json', evidence/(str(sequence)+'-receipt.json'))
            signed.append(output)
        producer_root = h.managed.state_root(record, baseline)
        producer_inventory = digest_json(inventory_tree(producer_root, state_snapshot=True))
        with fresh_consumer(work) as home:
            cache = home/'trusted-cache'; state_dir = home/'oci-state'
            if kind == 'flatpak':
                # Install only the pinned runtime. The application must be
                # installed by the real signed-release deployment below.
                target = baseline['entry']['plan']['target']; runtime = target['platform']+'/'+target['architecture']+'/'+target['branch']
                h.run_flatpak(['remote-add', '--user', '--if-not-exists', 'flathub', target['remoteUrl']], store=Path(os.environ['FLATPAK_USER_DIR']))
                h.run_flatpak(['install', '--user', '--noninteractive', '--assumeyes', '--no-related', 'flathub', runtime], store=Path(os.environ['FLATPAK_USER_DIR']))
                h.run_flatpak(['update', '--user', '--noninteractive', '--assumeyes', '--no-related', '--commit='+target['platformCommit'], runtime], store=Path(os.environ['FLATPAK_USER_DIR']))
            def cli(operation, value=app, *extra, accept=None):
                args = [sys.executable, '-m', 'cage', 'release', operation, value, '--key', key, '--format', kind, '--cache-dir', cache]
                if accept: args += ['--accept-permissions', accept]
                return h.command([*args, *extra], evidence/(operation+'-'+str(len(result['sessions']))+'.log'), timeout=240)
            def reject(args, label, contains):
                proc = subprocess.run(list(map(str, args)), text=True, capture_output=True, timeout=240)
                h.write(evidence/(label+'.json'), {'exitCode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr})
                assert proc.returncode != 0 and contains in proc.stdout+proc.stderr, (label, proc.stdout, proc.stderr)
            # Kill only this disposable installer immediately after its real
            # native deployment. The durable pending record must block launch
            # and recover must finish acceptance plus desktop registration.
            crash_code = ('import os,sys\nfrom artifact import release_v2\nfrom cage.cli import main\n'
                          'original=release_v2._install\n'
                          'def interrupted(*args,**kwargs):\n original(*args,**kwargs)\n os._exit(73)\n'
                          'release_v2._install=interrupted\nsys.exit(main(sys.argv[1:]))\n')
            crash_args = [sys.executable, '-c', crash_code, 'release', 'install', signed[0], '--key', key,
                          '--format', kind, '--cache-dir', cache, '--accept-permissions', baseline['entry']['plan']['capabilities']['contractDigest'],
                          *(['--state-dir', state_dir] if kind == 'oci' else [])]
            crashed = subprocess.run(list(map(str, crash_args)), capture_output=True, text=True, timeout=240)
            h.write(evidence/'interrupted-install.json', {'exitCode': crashed.returncode, 'stdout': crashed.stdout, 'stderr': crashed.stderr})
            assert crashed.returncode == 73, crashed.stderr
            ledger = release_install.installation(cache, app, kind)
            assert release_install._read(ledger)['pending']['action'] == 'install'
            reject([sys.executable, '-m', 'cage', 'release', 'run', app, '--format', kind, '--key', key, '--cache-dir', cache],
                   'pending-install-blocks-launch', 'pending')
            cli('recover')
            record = release_install._read(ledger)
            assert not record.get('pending')
            result['interruptedInstallRecovered'] = True
            current = releases.cached_release(cache/'releases'/record['activeReleaseDigest'], key, kind)
            root = h.managed.state_root(record, current)
            integration = authority.read_authority(app)['desktopEntry']; desktop = Path(integration['path'])
            assert integration['format'] == kind and releases.hash_file(desktop) == integration['sha256']
            def installed_run(counter, case, label, desktop_launch=False):
                rec, rel, _ = permissions.installed(app, kind)
                document = paths['replacement' if case == 'rebound' else 'write']/'canary'
                def launch(log):
                    if desktop_launch:
                        # Parse the installed Exec field and expand only the
                        # documented %F placeholder. No shell or generated substitute.
                        line = next(x[5:] for x in desktop.read_text().splitlines() if x.startswith('Exec='))
                        args = shlex.split(line); assert args[-1] == '%F'; args[-1:] = [str(document)]
                    else:
                        args = [sys.executable, '-m', 'cage', 'release', 'run', app, '--format', kind, '--key', key, '--cache-dir', cache, '--', document]
                    h.command(args, log, timeout=240)
                value, _, win = h.run_case(rel, rec, work, paths, case, port, abstract, device, host_process, shm,
                                           evidence/'consumer'/label, counter, launch=launch, setup=False)
                assert win['forwardedDocumentReadable'] is True
                result['sessions'].append({**value, 'operation': label, 'releaseDigest': rel['digest'], 'desktopExec': desktop_launch})
                h.write(evidence/'installed-release.json', result)
                return value
            installed_run(1, 'shared-all', 'fresh-install-desktop', True)
            generation = (root/'state.json').read_bytes()
            recovery = home/'retained-recovery'; shutil.copytree(root/_read_generations(root)['active'], recovery, symlinks=True, copy_function=copy_file)
            recovery_hash = digest_json(inventory_tree(recovery, state_snapshot=True))
            # A changed contract must be explicitly accepted before update.
            reject([sys.executable, '-m', 'cage', 'release', 'update', signed[1], '--format', kind, '--key', key, '--cache-dir', cache],
                   'unaccepted-policy', 'accept-permissions')
            cli('update', signed[1], accept=variant['entry']['plan']['capabilities']['contractDigest'])
            installed_run(2, 'shared-all', 'compatible-policy-update', True)
            # Native CLI is the independent operator, never Cage override code.
            h.configure(app, kind, paths, False, False, evidence/'operator-revocation', devices=False)
            # configure creates a test receipt; acceptance stays explicit.
            h.command([sys.executable, '-m', 'cage', 'permissions', 'accept', app, '--format', kind, '--contract', variant['entry']['plan']['capabilities']['contractDigest']], evidence/'accept-revoked.log')
            cli('rollback')
            reject([sys.executable, '-m', 'cage', 'release', 'run', app, '--format', kind, '--key', key, '--cache-dir', cache],
                   'historical-contract-needs-review', 'accept')
            h.command([sys.executable, '-m', 'cage', 'permissions', 'accept', app, '--format', kind, '--contract', baseline['entry']['plan']['capabilities']['contractDigest']], evidence/'accept-historical.log')
            installed_run(3, 'isolated', 'rollback-keeps-revocations', True)
            # Bind must preview, leave the receipt unchanged, then verify the
            # independent native edit. Other formats adopt directly.
            before = permissions.bindings_path(app, kind).read_bytes()
            loc = {'base': 'absolute', 'path': str(paths['replacement'])}
            binding = permissions.bind(app, kind, 'write-files', loc); h.write(evidence/'binding-preview.json', binding)
            if kind == 'flatpak':
                assert not binding['adopted'] and permissions.bindings_path(app, kind).read_bytes() == before
                h.command(binding['nativeCommand'], evidence/'operator-rebind.log')
                binding = permissions.bind(app, kind, 'write-files', loc)
            assert binding['adopted'] and binding['nativeOverridesWritten'] is False
            # Rebound tests expect networking/devices granted; retain revocation
            # coverage above and explicitly restore just the test's decisions.
            local = permissions.local_bindings(app, kind)
            local['decisions'] = {}
            _write_state_record(permissions.bindings_path(app, kind), local)
            if kind == 'flatpak':
                h.command(['flatpak', 'override', '--user', '--share=network', app], evidence/'operator-restore.log')
            h.command([sys.executable, '-m', 'cage', 'permissions', 'accept', app, '--format', kind, '--contract', baseline['entry']['plan']['capabilities']['contractDigest']], evidence/'accept-rebound.log')
            installed_run(4, 'rebound', 'native-folder-rebind', True)
            cli('recover')
            installed_run(5, 'rebound', 'recovery-relaunch', True)
            reject([sys.executable, '-m', 'cage', 'release', 'update', signed[0], '--format', kind, '--key', key, '--cache-dir', cache],
                   'stale-sequence', 'stale')
            final = release_install._read(ledger)
            assert final['highWater'] == 2 and len(final['releases']) == 2 and not final.get('pending')
            assert (root/'state.json').read_bytes() == generation, 'compatible operations changed prefix generations'
            assert digest_json(inventory_tree(recovery, state_snapshot=True)) == recovery_hash
            assert all((paths[x]/'canary').read_bytes() == b'cage-probe-canary\n' for x in ('write', 'replacement'))
            assert len({x['activePrefix'] for x in result['sessions']}) == 1
            h.write(evidence/'consumer-ledger.json', final)
            h.write(evidence/'consumer-generations.json', _read_generations(root))
            result.update(recoveryPreserved=True, generationRecordPreserved=True, publisherKeySha256=final['publisherKeySha256'],
                          highWater=final['highWater'], desktopExecFormats=[kind])
        # Back in the producer's untouched environment, adopt the exact already
        # observed native package and prefix through the public signed API.
        assert digest_json(inventory_tree(producer_root, state_snapshot=True)) == producer_inventory
        extra = ['--state-dir', work/'oci-state'] if kind == 'oci' else []
        h.command([sys.executable, '-m', 'cage', 'release', 'install', signed[0], '--key', key, '--format', kind,
                   '--cache-dir', work/'trusted-cache', '--accept-permissions', baseline['entry']['plan']['capabilities']['contractDigest'],
                   '--adopt-existing', *extra], evidence/'verified-adoption.log', timeout=240)
        assert digest_json(inventory_tree(producer_root, state_snapshot=True)) == producer_inventory
        result['verifiedAdoptionPreservedState'] = True
        result['status'] = 'passed'
    except BaseException as exc:
        result['status'] = 'failed'; result['error'] = str(exc); raise
    finally:
        h.write(evidence/'installed-release.json', result)
    return result
