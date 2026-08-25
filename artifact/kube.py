"""Kubernetes manifest export for Cage application images.

This module only emits manifests. It does not call kubectl or mutate a cluster.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from artifact.inspection import verify_bundle
from artifact.oci import ARTIFACT_IMAGE_SCHEMA_VERSION, EXPORTS_ROOT, STATE_ROOT

KUBE_EXPORT_SCHEMA_VERSION = 'cage.kube-export/v0'
SUPPORTED_NETWORK_MODES = {'none', 'bridge', 'host'}


class KubeExportError(RuntimeError):
    """Raised when a Cage bundle cannot be exported as Kubernetes YAML."""


def create_kube_export_plan(
    bundle_path: Path | str,
    *,
    image: str,
    namespace: str = 'default',
    name: str | None = None,
    state_size: str = '10Gi',
    exports_size: str = '10Gi',
    no_pvc: bool = False,
    replicas: int = 1,
    graphics: str = 'headless',
    allow_mutable_tag: bool = False,
    image_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a Kubernetes export plan for a verified Cage bundle."""
    bundle = Path(bundle_path)
    verification = verify_bundle(bundle)
    if not verification.get('valid'):
        raise KubeExportError('invalid Cage bundle: ' + _verification_error_text(verification))

    _validate_image_ref(image, allow_mutable_tag=allow_mutable_tag)

    manifest = _load_json(bundle / 'manifest.cage.json')
    graph = _load_json(bundle / 'metadata/graph.json')
    application = dict(graph.get('application') or {
        'name': manifest.get('name'),
        'version': manifest.get('version'),
    })
    app_name = str(application.get('name') or bundle.name)
    app_version = str(application.get('version') or '')
    resource_name = _k8s_name(name or app_name)
    labels = _labels(resource_name, app_name, app_version)
    annotations = _annotations(app_name, app_version, image)
    network_mode = _network_mode(graph)
    graph_graphics = dict(graph.get('graphics') or {})
    supported_graphics = set(graph_graphics.get('supportedModes') or [])
    if graphics not in supported_graphics:
        raise KubeExportError(
            f"graphics mode {graphics!r} is not supported by bundle graph"
        )
    if graphics == 'selkies' and network_mode != 'bridge':
        raise KubeExportError(
            "graphics selkies requires runtime.network bridge for pod HTTPS access"
        )
    if graphics == 'selkies':
        if replicas != 1:
            raise KubeExportError("graphics selkies requires exactly one replica")
        _validate_selkies_image_verification(image, image_verification)
    wine_graphics = str(graph_graphics.get('wineGraphics') or 'xwayland')
    if graphics == 'headless' and wine_graphics == 'wayland':
        raise KubeExportError('native Wine Wayland requires graphics selkies')

    resources: list[dict[str, Any]] = []
    if not no_pvc:
        resources.append(_pvc(f'{resource_name}-state', namespace, labels, annotations, state_size))
        resources.append(_pvc(f'{resource_name}-exports', namespace, labels, annotations, exports_size))
    if network_mode == 'none':
        resources.append(_deny_egress_policy(f'{resource_name}-deny-egress', namespace, labels, annotations))
    if graphics == 'selkies':
        resources.append(_deny_ingress_policy(f'{resource_name}-deny-ingress', namespace, labels, annotations))
        resources.append(_selkies_service(resource_name, namespace, labels, annotations))
    resources.append(_deployment(
        name=resource_name,
        namespace=namespace,
        labels=labels,
        annotations=annotations,
        image=image,
        no_pvc=no_pvc,
        replicas=replicas,
        graphics=graphics,
        wine_graphics=wine_graphics,
        network=network_mode,
    ))
    manifest_yaml = render_kube_yaml(resources)

    return {
        'schemaVersion': KUBE_EXPORT_SCHEMA_VERSION,
        'bundle': str(bundle),
        'application': application,
        'image': {
            'ref': image,
            'digestPinned': _is_digest_pinned(image),
            'mutableTagAllowed': bool(allow_mutable_tag),
        },
        'namespace': namespace,
        'name': resource_name,
        'replicas': replicas,
        'network': {
            'mode': network_mode,
            'hostNetwork': network_mode == 'host',
            'denyEgress': network_mode == 'none',
        },
        'state': {
            'enabled': True,
            'persistent': not no_pvc,
            'size': state_size,
            'mountPath': STATE_ROOT,
            'claimName': None if no_pvc else f'{resource_name}-state',
        },
        'exports': {
            'enabled': True,
            'persistent': not no_pvc,
            'size': exports_size,
            'mountPath': EXPORTS_ROOT,
            'claimName': None if no_pvc else f'{resource_name}-exports',
            'declared': manifest.get('exports', []),
        },
        'labels': labels,
        'annotations': annotations,
        'resources': resources,
        'manifestYaml': manifest_yaml,
        'verification': {
            'schemaVersion': verification.get('schemaVersion'),
            'valid': True,
            'warnings': verification.get('warnings', []),
        },
    }


def export_kube_manifest(
    bundle_path: Path | str,
    *,
    image: str,
    output_path: Path | str,
    namespace: str = 'default',
    name: str | None = None,
    state_size: str = '10Gi',
    exports_size: str = '10Gi',
    no_pvc: bool = False,
    replicas: int = 1,
    graphics: str = 'headless',
    allow_mutable_tag: bool = False,
    image_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write Kubernetes YAML for a Cage application image and return a summary."""
    plan = create_kube_export_plan(
        bundle_path,
        image=image,
        namespace=namespace,
        name=name,
        state_size=state_size,
        exports_size=exports_size,
        no_pvc=no_pvc,
        replicas=replicas,
        graphics=graphics,
        allow_mutable_tag=allow_mutable_tag,
        image_verification=image_verification,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(plan['manifestYaml'], encoding='utf-8')
    result = dict(plan)
    result['output'] = str(output)
    return result


def render_kube_yaml(resources: list[dict[str, Any]]) -> str:
    """Render Kubernetes resources as simple YAML documents."""
    return '\n---\n'.join(_dump_yaml(resource) for resource in resources) + '\n'


def _pvc(
    name: str,
    namespace: str,
    labels: dict[str, str],
    annotations: dict[str, str],
    size: str,
) -> dict[str, Any]:
    return {
        'apiVersion': 'v1',
        'kind': 'PersistentVolumeClaim',
        'metadata': {
            'name': name,
            'namespace': namespace,
            'labels': labels,
            'annotations': annotations,
        },
        'spec': {
            'accessModes': ['ReadWriteOnce'],
            'resources': {
                'requests': {
                    'storage': size,
                },
            },
        },
    }


def _selkies_service(
    name: str,
    namespace: str,
    labels: dict[str, str],
    annotations: dict[str, str],
) -> dict[str, Any]:
    return {
        'apiVersion': 'v1',
        'kind': 'Service',
        'metadata': {
            'name': name,
            'namespace': namespace,
            'labels': labels,
            'annotations': annotations,
        },
        'spec': {
            'type': 'ClusterIP',
            'selector': {'app.kubernetes.io/instance': name},
            'ports': [{'name': 'https', 'port': 3001, 'targetPort': 3001}],
        },
    }


def _deployment(
    *,
    name: str,
    namespace: str,
    labels: dict[str, str],
    annotations: dict[str, str],
    image: str,
    no_pvc: bool,
    replicas: int,
    graphics: str,
    wine_graphics: str,
    network: str,
) -> dict[str, Any]:
    state_volume = {'name': 'cage-state'}
    exports_volume = {'name': 'cage-exports'}
    config_volume = {'name': 'cage-config', 'emptyDir': {}}
    if no_pvc:
        state_volume['emptyDir'] = {}
        exports_volume['emptyDir'] = {}
    else:
        state_volume['persistentVolumeClaim'] = {'claimName': f'{name}-state'}
        exports_volume['persistentVolumeClaim'] = {'claimName': f'{name}-exports'}


    container = {
        'name': 'cage-app',
        'image': image,
        'imagePullPolicy': 'IfNotPresent',
        'env': [
            {'name': 'CAGE_STATE', 'value': STATE_ROOT},
            {'name': 'CAGE_EXPORTS', 'value': EXPORTS_ROOT},
            {'name': 'CAGE_GRAPHICS', 'value': graphics},
            {'name': 'CAGE_SESSION_MODE', 'value': graphics},
            {'name': 'CAGE_WINE_GRAPHICS', 'value': wine_graphics},
        ],
        'volumeMounts': [
            {'name': 'cage-state', 'mountPath': STATE_ROOT},
            {'name': 'cage-exports', 'mountPath': EXPORTS_ROOT},
        ],
    }
    volumes = [state_volume, exports_volume]
    if graphics == 'selkies':
        container['env'].extend([
            {'name': 'PUID', 'value': '1000'},
            {'name': 'PGID', 'value': '1000'},
        ])
        container['command'] = ['/init']
        container['ports'] = [{'name': 'https', 'containerPort': 3001, 'protocol': 'TCP'}]
        container['securityContext'] = {
            'runAsUser': 0,
            'runAsGroup': 0,
            'runAsNonRoot': False,
            'allowPrivilegeEscalation': False,
            'privileged': False,
            'capabilities': {'drop': ['ALL'], 'add': ['CHOWN', 'SETGID', 'SETUID']},
            'seccompProfile': {'type': 'RuntimeDefault'},
        }
        container['volumeMounts'].append({'name': 'cage-config', 'mountPath': '/config'})
        volumes.append(config_volume)

    return {
        'apiVersion': 'apps/v1',
        'kind': 'Deployment',
        'metadata': {
            'name': name,
            'namespace': namespace,
            'labels': labels,
            'annotations': annotations,
        },
        'spec': {
            'replicas': replicas,
            'selector': {
                'matchLabels': {
                    'app.kubernetes.io/instance': name,
                },
            },
            'template': {
                'metadata': {
                    'labels': labels,
                    'annotations': annotations,
                },
                'spec': {
                    'hostNetwork': network == 'host',
                    'containers': [container],
                    'volumes': volumes,
                },
            },
        },
    }


def _deny_ingress_policy(
    name: str,
    namespace: str,
    labels: dict[str, str],
    annotations: dict[str, str],
) -> dict[str, Any]:
    return {
        'apiVersion': 'networking.k8s.io/v1',
        'kind': 'NetworkPolicy',
        'metadata': {'name': name, 'namespace': namespace, 'labels': labels, 'annotations': annotations},
        'spec': {
            'podSelector': {'matchLabels': {'app.kubernetes.io/instance': labels['app.kubernetes.io/instance']}},
            'policyTypes': ['Ingress'],
            'ingress': [],
        },
    }


def _validate_selkies_image_verification(
    image: str,
    verification: dict[str, Any] | None,
) -> None:
    if not isinstance(verification, dict):
        raise KubeExportError(
            'graphics selkies requires a valid cage image verify receipt for the exact image'
        )
    checks = verification.get('checks')
    if (
        verification.get('schemaVersion') != 'cage.oci-image-verification/v0'
        or verification.get('success') is not True
        or verification.get('valid') is not True
        or verification.get('errors') not in ([], None)
        or not isinstance(checks, list)
        or not checks
        or any(not isinstance(check, dict) or check.get('ok') is not True for check in checks)
    ):
        raise KubeExportError('Selkies image verification receipt is incomplete or failed')
    if verification.get('imageRef') != image:
        raise KubeExportError('Selkies image verification receipt does not match --image')
    artifact = verification.get('artifactMetadata')
    if not isinstance(artifact, dict) or artifact.get('imageGraphics') != 'selkies':
        raise KubeExportError('verified OCI image is not a Selkies application image')


def _deny_egress_policy(
    name: str,
    namespace: str,
    labels: dict[str, str],
    annotations: dict[str, str],
) -> dict[str, Any]:
    return {
        'apiVersion': 'networking.k8s.io/v1',
        'kind': 'NetworkPolicy',
        'metadata': {
            'name': name,
            'namespace': namespace,
            'labels': labels,
            'annotations': annotations,
        },
        'spec': {
            'podSelector': {
                'matchLabels': {
                    'app.kubernetes.io/instance': labels['app.kubernetes.io/instance'],
                },
            },
            'policyTypes': ['Egress'],
            'egress': [],
        },
    }


def _labels(instance: str, app_name: str, app_version: str) -> dict[str, str]:
    return {
        'app.kubernetes.io/name': _label_value(app_name),
        'app.kubernetes.io/instance': instance,
        'app.kubernetes.io/component': 'cage-app',
        'app.kubernetes.io/part-of': 'cage',
        'io.cage.app.name': _label_value(app_name),
        'io.cage.app.version': _label_value(app_version),
    }


def _annotations(app_name: str, app_version: str, image: str) -> dict[str, str]:
    return {
        'io.cage.schema': ARTIFACT_IMAGE_SCHEMA_VERSION,
        'io.cage.app.raw-name': app_name,
        'io.cage.app.version': app_version,
        'io.cage.image': image,
    }


def _validate_image_ref(image: str, *, allow_mutable_tag: bool) -> None:
    if not image:
        raise KubeExportError('Kubernetes export requires an OCI image reference')
    if not _is_digest_pinned(image) and not allow_mutable_tag:
        raise KubeExportError(
            'Kubernetes export requires a digest-pinned image reference like '
            'ghcr.io/org/app@sha256:...; pass --allow-mutable-tag to override'
        )


def _is_digest_pinned(image: str) -> bool:
    return re.fullmatch(r'[^@\s]+@sha256:[0-9a-f]{64}', image) is not None


def _network_mode(graph: dict[str, Any]) -> str:
    runtime = graph.get('runnerRuntime') or {}
    network = runtime['network'] if 'network' in runtime else 'none'
    if not isinstance(network, str) or network not in SUPPORTED_NETWORK_MODES:
        allowed = ', '.join(sorted(SUPPORTED_NETWORK_MODES))
        raise KubeExportError(f'bundle graph runnerRuntime.network must be one of: {allowed}')
    return network


def _k8s_name(value: str) -> str:
    name = re.sub(r'[^a-z0-9-]+', '-', value.lower()).strip('-')
    name = re.sub(r'-+', '-', name)[:63].strip('-')
    return name or 'cage-app'


def _label_value(value: str) -> str:
    # Keep labels lowercase/DNS-ish for broad Kubernetes tooling compatibility.
    # Exact Cage metadata is preserved separately in annotations.
    text = re.sub(r'[^a-z0-9.-]+', '-', str(value).lower()).strip('-.')[:63].strip('-.')
    return text or 'cage-app'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _verification_error_text(verification: dict[str, Any]) -> str:
    errors = verification.get('errors') or []
    if errors:
        return '; '.join(str(error) for error in errors)
    return 'verification failed'


def _dump_yaml(value: Any, indent: int = 0) -> str:
    lines: list[str] = []
    _emit_yaml(value, lines, indent)
    return '\n'.join(lines)


def _emit_yaml(value: Any, lines: list[str], indent: int) -> None:
    prefix = ' ' * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if item == {}:
                lines.append(f'{prefix}{key}: {{}}')
            elif item == []:
                lines.append(f'{prefix}{key}: []')
            elif isinstance(item, (dict, list)):
                lines.append(f'{prefix}{key}:')
                _emit_yaml(item, lines, indent + 2)
            else:
                lines.append(f'{prefix}{key}: {_yaml_scalar(item)}')
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                if not item:
                    lines.append(f'{prefix}- {{}}')
                    continue
                first = True
                for key, nested in item.items():
                    if first:
                        if nested == {}:
                            lines.append(f'{prefix}- {key}: {{}}')
                        elif nested == []:
                            lines.append(f'{prefix}- {key}: []')
                        elif isinstance(nested, (dict, list)):
                            lines.append(f'{prefix}- {key}:')
                            _emit_yaml(nested, lines, indent + 4)
                        else:
                            lines.append(f'{prefix}- {key}: {_yaml_scalar(nested)}')
                        first = False
                    else:
                        if nested == {}:
                            lines.append(f'{prefix}  {key}: {{}}')
                        elif nested == []:
                            lines.append(f'{prefix}  {key}: []')
                        elif isinstance(nested, (dict, list)):
                            lines.append(f'{prefix}  {key}:')
                            _emit_yaml(nested, lines, indent + 4)
                        else:
                            lines.append(f'{prefix}  {key}: {_yaml_scalar(nested)}')
            elif isinstance(item, list):
                lines.append(f'{prefix}-')
                _emit_yaml(item, lines, indent + 2)
            else:
                lines.append(f'{prefix}- {_yaml_scalar(item)}')
    else:
        lines.append(f'{prefix}{_yaml_scalar(value)}')


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if value is None:
        return 'null'
    text = str(value)
    # Keep common Kubernetes strings readable. Quote only problematic YAML scalars.
    if text == '' or text[0] in '{[&*#?|-<>=!%@`' or text.strip() != text or ': ' in text:
        return json.dumps(text)
    lowered = text.lower()
    if lowered in {'true', 'false', 'null', '~'}:
        return json.dumps(text)
    return text
