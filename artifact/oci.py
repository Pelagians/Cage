'''OCI application image export for Cage bundles.

Phase 5B/5C turns a verified Cage execution bundle into a runnable
application OCI image. The image remains application-first: it embeds the
sealed bundle under /opt/cage/bundle and separates mutable runtime
state and exports under dedicated paths.
'''
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from artifact.inspection import verify_bundle

ARTIFACT_IMAGE_SCHEMA_VERSION = 'cage.artifact-image/v0'
OCI_EXPORT_PLAN_SCHEMA_VERSION = 'cage.oci-export-plan/v0'
OCI_EXPORT_RESULT_SCHEMA_VERSION = 'cage.oci-export-result/v0'
OCI_IMAGE_INSPECTION_SCHEMA_VERSION = 'cage.oci-image-inspection/v0'
OCI_IMAGE_VERIFICATION_SCHEMA_VERSION = 'cage.oci-image-verification/v0'

BUNDLE_ROOT = '/opt/cage/bundle'
STATE_ROOT = '/var/lib/cage/state'
EXPORTS_ROOT = '/exports'
APP_LAUNCHER = '/usr/local/bin/cage-app-launch'


class OCIExportError(RuntimeError):
    '''Raised when a bundle cannot be exported as an OCI application image.'''


def create_oci_export_plan(bundle_path: Path | str, *, tag: str) -> dict[str, Any]:
    '''Return a dry-run plan for exporting *bundle_path* as a runnable OCI image.'''
    bundle = Path(bundle_path)
    verification = verify_bundle(bundle)
    if not verification.get('valid'):
        raise OCIExportError('invalid Cage bundle: ' + _verification_error_text(verification))
    if not verification.get('runnable'):
        classification = verification.get('classification', 'non-runnable-artifact')
        state = (verification.get('status') or {}).get('state')
        raise OCIExportError(
            f'Cage bundle is not runnable: classification={classification}, state={state}'
        )

    manifest = _load_json(bundle, 'manifest.cage.json')
    graph = _load_json(bundle, 'metadata/graph.json')
    runtime = dict(graph.get('runnerRuntime') or {})
    launch = dict(graph.get('launch') or {})
    application = dict(graph.get('application') or {
        'name': manifest.get('name'),
        'version': manifest.get('version'),
    })
    base_image = _runtime_image(runtime)
    artifact_metadata = _artifact_metadata(
        bundle=bundle,
        tag=tag,
        application=application,
        manifest=manifest,
        graph=graph,
        runtime=runtime,
        launch=launch,
        base_image=base_image,
    )
    labels = _oci_labels(application, runtime, base_image)
    containerfile = _containerfile(base_image, labels, dict(runtime.get('environment') or {}))

    return {
        'schemaVersion': OCI_EXPORT_PLAN_SCHEMA_VERSION,
        'imageType': 'runnable-application-image',
        'bundle': str(bundle),
        'tag': tag,
        'baseImage': base_image,
        'application': application,
        'runtime': _runtime_summary(runtime),
        'layout': {
            'bundle': BUNDLE_ROOT,
            'state': STATE_ROOT,
            'exports': EXPORTS_ROOT,
            'entrypoint': APP_LAUNCHER,
            'artifactMetadata': f'{BUNDLE_ROOT}/metadata/artifact.json',
        },
        'labels': labels,
        'artifactMetadata': artifact_metadata,
        'containerfile': {
            'path': 'Containerfile',
            'content': containerfile,
        },
        'launcher': {
            'path': 'cage-app-launch',
            'containerPath': APP_LAUNCHER,
        },
        'verification': {
            'schemaVersion': verification.get('schemaVersion'),
            'valid': True,
            'runnable': True,
            'warnings': verification.get('warnings', []),
        },
    }


def prepare_oci_build_context(
    bundle_path: Path | str,
    plan: dict[str, Any],
    context_dir: Path | str,
) -> Path:
    '''Stage a container build context for *plan* and return its path.'''
    bundle = Path(bundle_path)
    context = Path(context_dir)
    if context.exists():
        if any(context.iterdir()):
            raise OCIExportError(
                f'OCI build context already exists and is not empty: {context}'
            )
    else:
        context.mkdir(parents=True)

    staged_bundle = context / 'bundle'
    shutil.copytree(bundle, staged_bundle, symlinks=True)
    _write_json(staged_bundle / 'metadata/artifact.json', plan['artifactMetadata'])

    containerfile = context / plan['containerfile']['path']
    containerfile.write_text(plan['containerfile']['content'], encoding='utf-8')

    launcher = context / plan['launcher']['path']
    launcher.write_text(_launcher_script(), encoding='utf-8')
    launcher.chmod(0o755)
    return context


def export_oci_image(
    bundle_path: Path | str,
    *,
    tag: str,
    engine: str | None = None,
    context_dir: Path | str | None = None,
    timeout: int = 600,
    push: bool = False,
) -> dict[str, Any]:
    '''Build a runnable application OCI image from a verified Cage bundle.'''
    bundle = Path(bundle_path)
    plan = create_oci_export_plan(bundle, tag=tag)
    selected_engine = _select_engine(engine)
    if selected_engine is None:
        requested = engine or 'podman/docker'
        return _result(
            success=False,
            plan=plan,
            engine=requested,
            context=None,
            command=[],
            exit_code=None,
            stdout='',
            stderr='',
            error=f'container build engine not found: {requested}',
        )

    context = prepare_oci_build_context(
        bundle,
        plan,
        Path(context_dir) if context_dir is not None else Path(tempfile.mkdtemp(prefix='cage-oci-')),
    )
    containerfile_path = context / plan['containerfile']['path']
    command = [selected_engine, 'build', '-f', str(containerfile_path), '-t', tag, str(context)]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return _result(
            success=False,
            plan=plan,
            engine=selected_engine,
            context=context,
            command=command,
            exit_code=None,
            stdout='',
            stderr='',
            error=f'container build engine not found: {selected_engine}: {exc}',
        )
    except subprocess.TimeoutExpired as exc:
        return _result(
            success=False,
            plan=plan,
            engine=selected_engine,
            context=context,
            command=command,
            exit_code=None,
            stdout=exc.stdout or '',
            stderr=exc.stderr or '',
            error=f'OCI image build timed out after {timeout}s',
        )

    result = _result(
        success=proc.returncode == 0,
        plan=plan,
        engine=selected_engine,
        context=context,
        command=command,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        error=None if proc.returncode == 0 else 'OCI image build failed',
    )
    if push and proc.returncode == 0:
        push_command = [selected_engine, 'push', tag]
        push_proc = subprocess.run(
            push_command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        result['push'] = {
            'command': push_command,
            'exitCode': push_proc.returncode,
            'stdout': push_proc.stdout,
            'stderr': push_proc.stderr,
            'success': push_proc.returncode == 0,
        }
        result['success'] = result['success'] and push_proc.returncode == 0
        if push_proc.returncode != 0:
            result['error'] = 'OCI image push failed'
        else:
            image_identity = inspect_oci_image(tag, engine=selected_engine, timeout=timeout)
            result['image'] = image_identity
            if image_identity.get('success') and image_identity.get('digest'):
                result['push']['digest'] = image_identity['digest']
                result['push']['repoDigests'] = image_identity.get('repoDigests', [])
            else:
                result['success'] = False
                result['error'] = 'OCI image push succeeded but no repo digest was recorded'
    return result


def inspect_oci_image(
    image_ref: str,
    *,
    engine: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    '''Inspect a local OCI image and return digest/label identity metadata.'''
    selected_engine = _select_engine(engine)
    requested = engine or 'podman/docker'
    if selected_engine is None:
        return {
            'schemaVersion': OCI_IMAGE_INSPECTION_SCHEMA_VERSION,
            'success': False,
            'imageRef': image_ref,
            'engine': requested,
            'command': [],
            'errors': [f'container build engine not found: {requested}'],
            'warnings': [],
        }

    command = [selected_engine, 'image', 'inspect', image_ref]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            'schemaVersion': OCI_IMAGE_INSPECTION_SCHEMA_VERSION,
            'success': False,
            'imageRef': image_ref,
            'engine': selected_engine,
            'command': command,
            'errors': [f'container build engine not found: {selected_engine}: {exc}'],
            'warnings': [],
        }

    if proc.returncode != 0:
        return {
            'schemaVersion': OCI_IMAGE_INSPECTION_SCHEMA_VERSION,
            'success': False,
            'imageRef': image_ref,
            'engine': selected_engine,
            'command': command,
            'exitCode': proc.returncode,
            'stdout': proc.stdout,
            'stderr': proc.stderr,
            'errors': ['OCI image inspect failed'],
            'warnings': [],
        }

    try:
        parsed = json.loads(proc.stdout)
        record = parsed[0] if isinstance(parsed, list) and parsed else parsed
    except (json.JSONDecodeError, TypeError, IndexError) as exc:
        return {
            'schemaVersion': OCI_IMAGE_INSPECTION_SCHEMA_VERSION,
            'success': False,
            'imageRef': image_ref,
            'engine': selected_engine,
            'command': command,
            'exitCode': proc.returncode,
            'stdout': proc.stdout,
            'stderr': proc.stderr,
            'errors': [f'OCI image inspect returned invalid JSON: {exc}'],
            'warnings': [],
        }

    repo_digests = list(record.get('RepoDigests') or [])
    labels = dict((record.get('Config') or {}).get('Labels') or {})
    digest = _digest_from_repo_digests(repo_digests)
    return {
        'schemaVersion': OCI_IMAGE_INSPECTION_SCHEMA_VERSION,
        'success': True,
        'imageRef': image_ref,
        'engine': selected_engine,
        'command': command,
        'imageId': record.get('Id'),
        'repoDigests': repo_digests,
        'digest': digest,
        'labels': labels,
        'warnings': [] if digest else ['image has no repo digest recorded locally'],
        'errors': [],
    }


def verify_oci_image_metadata(
    image_ref: str,
    *,
    engine: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    '''Verify OCI labels match embedded Cage artifact metadata.'''
    selected_engine = _select_engine(engine)
    requested = engine or 'podman/docker'
    if selected_engine is None:
        return _image_verification_result(
            image_ref=image_ref,
            engine=requested,
            image=None,
            artifact=None,
            checks=[],
            errors=[f'container build engine not found: {requested}'],
            warnings=[],
        )

    image = inspect_oci_image(image_ref, engine=selected_engine, timeout=timeout)
    if not image.get('success'):
        return _image_verification_result(
            image_ref=image_ref,
            engine=selected_engine,
            image=image,
            artifact=None,
            checks=[],
            errors=list(image.get('errors') or ['OCI image inspect failed']),
            warnings=list(image.get('warnings') or []),
        )

    cat_command = [
        selected_engine, 'run', '--rm', '--entrypoint', '/bin/cat',
        image_ref, f'{BUNDLE_ROOT}/metadata/artifact.json',
    ]
    proc = subprocess.run(
        cat_command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        return _image_verification_result(
            image_ref=image_ref,
            engine=selected_engine,
            image=image,
            artifact=None,
            checks=[],
            errors=['unable to read embedded Cage artifact metadata from image'],
            warnings=list(image.get('warnings') or []),
            extra={'metadataCommand': cat_command, 'stderr': proc.stderr, 'stdout': proc.stdout},
        )

    try:
        artifact = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return _image_verification_result(
            image_ref=image_ref,
            engine=selected_engine,
            image=image,
            artifact=None,
            checks=[],
            errors=[f'embedded Cage artifact metadata is invalid JSON: {exc}'],
            warnings=list(image.get('warnings') or []),
            extra={'metadataCommand': cat_command, 'stdout': proc.stdout},
        )

    labels = image.get('labels') or {}
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def add_check(check_id: str, label_key: str, expected: Any) -> None:
        actual = labels.get(label_key)
        ok = str(actual) == str(expected)
        checks.append({
            'id': check_id,
            'ok': ok,
            'label': label_key,
            'actual': actual,
            'expected': expected,
        })
        if not ok:
            errors.append(
                f'label {label_key} mismatch: expected {expected!r}, got {actual!r}'
            )

    runtime = artifact.get('runtime') or {}
    application = artifact.get('application') or {}
    add_check('schema', 'io.cage.schema', artifact.get('schemaVersion'))
    add_check('app-name', 'io.cage.app.name', application.get('name'))
    add_check('app-version', 'io.cage.app.version', application.get('version'))
    add_check('runtime-provider', 'io.cage.runtime.provider', runtime.get('provider'))
    add_check('runtime-requested-version', 'io.cage.runtime.requestedVersion', runtime.get('requestedVersion'))
    add_check('runtime-resolved-version', 'io.cage.runtime.resolvedVersion', runtime.get('resolvedVersion'))
    add_check('runtime-base-image', 'io.cage.runtime.baseImage', runtime.get('baseImage'))
    add_check('runner', 'io.cage.runner', runtime.get('runner'))
    add_check('launcher', 'io.cage.launcher', runtime.get('launcher'))

    return _image_verification_result(
        image_ref=image_ref,
        engine=selected_engine,
        image=image,
        artifact=artifact,
        checks=checks,
        errors=errors,
        warnings=list(image.get('warnings') or []),
        extra={'metadataCommand': cat_command},
    )


# Backward-compatible mapping helper used by the existing `cage build` path.
def build_oci_image(
    bundle_path: Path,
    base_image: str,
    *,
    output_tag: str | None = None,
    build_cmd: str = 'docker',
) -> dict[str, Any]:
    dockerfile_content = (
        f'FROM {base_image}\n'
        '\n'
        'LABEL dev.cage.artifact.kind=execution-bundle\n'
        'LABEL dev.cage.artifact.version=v0\n'
        '\n'
        f'COPY {bundle_path.name} {BUNDLE_ROOT}\n'
    )
    return {
        'baseImage': base_image,
        'bundlePath': str(bundle_path),
        'outputTag': output_tag,
        'suggestedDockerfile': dockerfile_content,
    }


def _artifact_metadata(
    *,
    bundle: Path,
    tag: str,
    application: dict[str, Any],
    manifest: dict[str, Any],
    graph: dict[str, Any],
    runtime: dict[str, Any],
    launch: dict[str, Any],
    base_image: str,
) -> dict[str, Any]:
    return {
        'schemaVersion': ARTIFACT_IMAGE_SCHEMA_VERSION,
        'imageType': 'runnable-application-image',
        'application': application,
        'runtime': {
            **_runtime_summary(runtime),
            'baseImage': base_image,
            'localImage': runtime.get('localImage'),
        },
        'recipe': {
            'schemaVersion': manifest.get('schemaVersion'),
            'path': 'manifest.cage.json',
        },
        'launch': launch,
        'graphics': graph.get('graphics', {}),
        'compatibility': graph.get('compatibility', {}),
        'state': {
            **(manifest.get('state') or {'defaultPersistence': 'persistent'}),
            'path': STATE_ROOT,
        },
        'exports': {
            'path': EXPORTS_ROOT,
            'declared': manifest.get('exports', []),
        },
        'layout': {
            'bundle': BUNDLE_ROOT,
            'state': STATE_ROOT,
            'exports': EXPORTS_ROOT,
            'entrypoint': APP_LAUNCHER,
        },
        'sourceBundle': {
            'path': str(bundle),
            'graph': 'metadata/graph.json',
            'provenance': 'metadata/provenance.json',
        },
        'targetImage': {
            'tag': tag,
        },
    }


def _runtime_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    keys = [
        'provider', 'version', 'requestedVersion', 'resolvedVersion',
        'family', 'runner', 'runnerVersion', 'packageVersion',
        'launcher', 'launcherVersion', 'runtimeUsable', 'environment',
    ]
    return {key: runtime[key] for key in keys if key in runtime and runtime[key] is not None}


def _oci_labels(application: dict[str, Any], runtime: dict[str, Any], base_image: str) -> dict[str, str]:
    return {
        'org.opencontainers.image.title': str(application.get('name', 'cage-application')),
        'org.opencontainers.image.version': str(application.get('version', '')),
        'org.opencontainers.image.description': 'Cage runnable application image',
        'io.cage.schema': ARTIFACT_IMAGE_SCHEMA_VERSION,
        'io.cage.app.name': str(application.get('name', '')),
        'io.cage.app.version': str(application.get('version', '')),
        'io.cage.runtime.provider': str(runtime.get('provider', '')),
        'io.cage.runtime.requestedVersion': str(runtime.get('requestedVersion', runtime.get('version', ''))),
        'io.cage.runtime.resolvedVersion': str(runtime.get('resolvedVersion', runtime.get('version', ''))),
        'io.cage.runtime.baseImage': base_image,
        'io.cage.runner': str(runtime.get('runner', '')),
        'io.cage.launcher': str(runtime.get('launcher', '')),
    }


def _containerfile(
    base_image: str,
    labels: dict[str, str],
    environment: dict[str, str] | None = None,
) -> str:
    label_lines = '\n'.join(
        f'LABEL {key}={_docker_quote(value)}' for key, value in labels.items()
    )
    environment_lines = ''.join(
        f'ENV {key}={_docker_quote(value)}\n'
        for key, value in sorted((environment or {}).items())
    )
    return (
        f'FROM {base_image}\n'
        '\n'
        f'{label_lines}\n'
        '\n'
        f'{environment_lines}'
        f'ENV CAGE_BUNDLE={BUNDLE_ROOT} \\\n'
        f'    CAGE_STATE={STATE_ROOT} \\\n'
        f'    CAGE_EXPORTS={EXPORTS_ROOT} \\\n'
        f'    WINEPREFIX={STATE_ROOT}/prefix \\\n'
        '    CAGE_GRAPHICS=headless\n'
        '\n'
        f'COPY bundle {BUNDLE_ROOT}\n'
        f'COPY cage-app-launch {APP_LAUNCHER}\n'
        f'RUN chmod +x {APP_LAUNCHER} && mkdir -p {STATE_ROOT} {EXPORTS_ROOT}\n'
        f'VOLUME ["{STATE_ROOT}", "{EXPORTS_ROOT}"]\n'
        f'ENTRYPOINT ["{APP_LAUNCHER}"]\n'
    )


def _launcher_script() -> str:
    return f'''#!/usr/bin/env bash
set -euo pipefail

export CAGE_BUNDLE="${{CAGE_BUNDLE:-{BUNDLE_ROOT}}}"
export CAGE_STATE="${{CAGE_STATE:-{STATE_ROOT}}}"
export CAGE_EXPORTS="${{CAGE_EXPORTS:-{EXPORTS_ROOT}}}"
export WINEPREFIX="${{WINEPREFIX:-${{CAGE_STATE}}/prefix}}"
export CAGE_GRAPH="${{CAGE_GRAPH:-${{CAGE_BUNDLE}}/metadata/graph.json}}"
mkdir -p "$CAGE_STATE" "$CAGE_EXPORTS"

if [ ! -d "$WINEPREFIX/drive_c" ]; then
  rm -rf "$WINEPREFIX"
  mkdir -p "$(dirname "$WINEPREFIX")"
  cp -a "$CAGE_BUNDLE/prefix" "$WINEPREFIX"
fi

exec python3 - "$@" <<'PY'
import json
import os
import sys

bundle = os.environ.get("CAGE_BUNDLE", "{BUNDLE_ROOT}")
graph_path = os.environ.get("CAGE_GRAPH", os.path.join(bundle, "metadata", "graph.json"))
with open(graph_path, "r", encoding="utf-8") as handle:
    graph = json.load(handle)
runtime = graph.get("runnerRuntime", {{}})
launch = graph.get("launch", {{}})
compatibility = (graph.get("compatibility") or {{}}).get("requestedPolicy") or {{}}


def _compile_dll_policy(policy):
    aliases = {{
        "disabled": "disabled", "disable": "disabled", "off": "disabled", "none": "disabled",
        "native": "native", "n": "native",
        "builtin": "builtin", "b": "builtin",
        "native,builtin": "native,builtin", "n,b": "native,builtin", "native-first": "native,builtin",
        "builtin,native": "builtin,native", "b,n": "builtin,native", "builtin-first": "builtin,native",
    }}
    values = {{"disabled": "", "native": "n", "builtin": "b", "native,builtin": "n,b", "builtin,native": "b,n"}}
    parts = []
    for dll in sorted(policy or {{}}):
        raw = str(policy[dll]).strip().lower().replace(" ", "")
        normalized = aliases.get(raw)
        if normalized:
            parts.append(f"{{dll}}={{values[normalized]}}")
    return ";".join(parts)


def _compatibility_env(policy):
    env = {{}}
    if policy.get("arch"):
        env["WINEARCH"] = str(policy["arch"])
    graphics = policy.get("graphics") or {{}}
    if graphics.get("backend"):
        env["CAGE_GRAPHICS_BACKEND"] = str(graphics["backend"])
    if graphics.get("fallback"):
        env["CAGE_GRAPHICS_FALLBACK"] = str(graphics["fallback"])
    for key, value in (policy.get("env") or {{}}).items():
        env[str(key)] = str(value)
    overrides = _compile_dll_policy(policy.get("dllPolicy") or {{}})
    if overrides:
        env["WINEDLLOVERRIDES"] = overrides
    return env


for key, value in _compatibility_env(compatibility).items():
    os.environ[str(key)] = str(value)

launcher = runtime.get("launcher", "wine")
if launcher == "umu":
    executable = "umu-run"
elif launcher == "wine":
    executable = "wine"
else:
    raise SystemExit(f"unsupported Cage launcher: {{launcher}}")
for key, value in (launch.get("env") or {{}}).items():
    os.environ[str(key)] = str(value)
command = [executable, launch.get("entrypoint", "")] + list(launch.get("args") or []) + sys.argv[1:]
if not command[1]:
    raise SystemExit("Cage launch entrypoint is missing")
os.execvp(command[0], command)
PY
'''


def _select_engine(engine: str | None) -> str | None:
    candidates = [engine] if engine else ['podman', 'docker']
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    return None


def _result(
    *,
    success: bool,
    plan: dict[str, Any],
    engine: str,
    context: Path | None,
    command: list[str],
    exit_code: int | None,
    stdout: str,
    stderr: str,
    error: str | None,
) -> dict[str, Any]:
    result = {
        'schemaVersion': OCI_EXPORT_RESULT_SCHEMA_VERSION,
        'success': success,
        'tag': plan.get('tag'),
        'engine': engine,
        'context': str(context) if context is not None else None,
        'command': command,
        'exitCode': exit_code,
        'stdout': stdout,
        'stderr': stderr,
        'plan': plan,
    }
    if error:
        result['error'] = error
    return result


def _digest_from_repo_digests(repo_digests: list[str]) -> str | None:
    for ref in repo_digests:
        if '@sha256:' in ref:
            return 'sha256:' + ref.split('@sha256:', 1)[1]
    return None


def _image_verification_result(
    *,
    image_ref: str,
    engine: str,
    image: dict[str, Any] | None,
    artifact: dict[str, Any] | None,
    checks: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    valid = not errors and bool(checks or artifact is not None)
    result = {
        'schemaVersion': OCI_IMAGE_VERIFICATION_SCHEMA_VERSION,
        'success': valid,
        'valid': valid,
        'imageRef': image_ref,
        'engine': engine,
        'image': image,
        'artifactMetadata': artifact,
        'checks': checks,
        'errors': errors,
        'warnings': warnings,
    }
    if extra:
        result.update(extra)
    return result


def _runtime_image(runtime: dict[str, Any]) -> str:
    image = runtime.get('image') or runtime.get('ociImage')
    if not image:
        raise OCIExportError('bundle graph does not contain a runner runtime image')
    return str(image)


def _verification_error_text(verification: dict[str, Any]) -> str:
    errors = verification.get('errors') or []
    if errors:
        return '; '.join(str(error) for error in errors)
    return 'verification failed'


def _docker_quote(value: str) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _load_json(bundle: Path, rel: str) -> dict[str, Any]:
    return json.loads((bundle / rel).read_text(encoding='utf-8'))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
