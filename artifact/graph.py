"""Execution graph generation for Cage bundles.

The execution graph is the resolved, machine-readable contract that sits
between a declarative manifest and a runnable Cage bundle.  It keeps the
Ramalama-like concepts distinct:

- runtime OCI image selected from the catalog;
- application/prefix bundle as the workload artifact;
- launch contract and graphics/run policy;
- deterministic phase nodes/edges for build/run tooling.
"""
from __future__ import annotations
from typing import Any

from builder.pipeline import build_plan
from core.manifest import Manifest, resolve_module_capabilities
from runtime.providers import RuntimeBinding, resolve_manifest_runtime

SCHEMA_VERSION = "cage.execution-graph/v0"
DEFAULT_GRAPHICS_MODE = "headless"
SUPPORTED_GRAPHICS_MODES = ["headless", "vnc"]


def build_execution_graph(manifest: Manifest) -> dict[str, Any]:
    """Return a deterministic resolved execution graph for *manifest*."""
    runtime = resolve_manifest_runtime(manifest)
    runtime_node_id = _runtime_node_id(runtime)
    manifest_node_id = f"manifest:{manifest.name}:{manifest.version}"
    phase_plan = build_plan(manifest)
    phase_nodes = [_phase_node(phase) for phase in phase_plan]
    capabilities = resolve_module_capabilities(manifest.modules)

    builder_runtime_payload = _runtime_payload(runtime)
    runner_runtime_payload = dict(builder_runtime_payload)
    runner_runtime_payload["network"] = manifest.runtime.network
    build_payload = {"network": manifest.build.network}
    launch_payload = manifest.launch.to_dict() if manifest.launch else {"hasDefaultLaunch": False}

    nodes: list[dict[str, Any]] = [
        {
            "id": manifest_node_id,
            "kind": "manifest",
            "label": f"{manifest.name}:{manifest.version}",
            "application": {
                "name": manifest.name,
                "version": manifest.version,
            },
        },
        {
            "id": runtime_node_id,
            "kind": "runtime-image",
            "label": builder_runtime_payload["image"],
            "runtime": dict(builder_runtime_payload),
        },
        *phase_nodes,
        {
            "id": "prefix:wineprefix",
            "kind": "prefix",
            "label": "Wine prefix",
            "path": "prefix",
        },
        {
            "id": "launch:entrypoint",
            "kind": "launch",
            "label": manifest.launch.entrypoint if manifest.launch else "No default launch",
            "launch": launch_payload,
        },
        {
            "id": "artifact:bundle",
            "kind": "artifact",
            "label": f"{manifest.name}-{manifest.version}",
            "artifact": {
                "kind": "cage.bundle",
                "path": ".",
            },
        },
    ]

    edges: list[dict[str, str]] = [
        {"from": manifest_node_id, "to": runtime_node_id, "type": "resolves"},
        {"from": manifest_node_id, "to": "phase:init-prefix", "type": "provides"},
        {"from": runtime_node_id, "to": "phase:init-prefix", "type": "executes"},
    ]
    for left, right in zip(phase_plan, phase_plan[1:]):
        edges.append({
            "from": f"phase:{left['phase']}",
            "to": f"phase:{right['phase']}",
            "type": "precedes",
        })
    edges.extend([
        {"from": "phase:init-prefix", "to": "prefix:wineprefix", "type": "creates"},
        {"from": "prefix:wineprefix", "to": "phase:launch", "type": "mutates"},
        {"from": "launch:entrypoint", "to": "phase:launch", "type": "validates"},
        {"from": "phase:export", "to": "artifact:bundle", "type": "produces"},
    ])

    return {
        "schemaVersion": SCHEMA_VERSION,
        "application": {
            "name": manifest.name,
            "version": manifest.version,
        },
        "manifest": {
            "schemaVersion": manifest.schema_version,
            "path": "manifest.cage.json",
        },
        "artifact": {
            "kind": "cage.bundle",
            "path": ".",
        },
        "builderRuntime": dict(builder_runtime_payload),
        "build": build_payload,
        "runnerRuntime": dict(runner_runtime_payload),
        "graphics": {
            "defaultMode": DEFAULT_GRAPHICS_MODE,
            "supportedModes": SUPPORTED_GRAPHICS_MODES,
        },
        "launch": launch_payload,
        "entrypoints": [entrypoint if isinstance(entrypoint, dict) else entrypoint.to_dict() for entrypoint in manifest.entrypoints],
        "fileAssociations": [association if isinstance(association, dict) else association.to_dict() for association in manifest.file_associations],
        "compatibility": {
            "requiresExactRuntime": True,
            "policy": "exact-provider-version",
            "requestedPolicy": manifest.compatibility,
            "reason": (
                "Wine prefixes are stateful runtime artifacts; v0 bundles "
                "must run with the same provider/version used to build them."
            ),
        },
        "modules": _module_payloads(manifest),
        "capabilities": capabilities,
        "nodes": nodes,
        "edges": edges,
    }


def _runtime_payload(runtime: RuntimeBinding) -> dict[str, Any]:
    image = runtime.oci_image or runtime.local_oci_image
    payload = runtime.to_dict()
    payload["image"] = image
    payload["localImage"] = runtime.local_oci_image
    return {k: v for k, v in payload.items() if v is not None}


def _runtime_node_id(runtime: RuntimeBinding) -> str:
    return f"runtime:{runtime.provider}:{runtime.version}"


def _phase_node(phase: dict[str, object]) -> dict[str, Any]:
    name = str(phase["phase"])
    node: dict[str, Any] = {
        "id": f"phase:{name}",
        "kind": "build-phase",
        "label": name,
        "phase": name,
        "stepKind": phase.get("kind"),
        "description": phase.get("description"),
        "unsafe": bool(phase.get("unsafe", False)),
        "inputs": list(phase.get("inputs", [])),
        "actions": list(phase.get("actions", [])),
    }
    if phase.get("moduleType") is not None:
        node["moduleType"] = phase.get("moduleType")
        node["moduleIndex"] = phase.get("moduleIndex")
        node["stepIndex"] = phase.get("stepIndex")
    if phase.get("metadata") is not None:
        node["metadata"] = phase.get("metadata")
    return node


def _module_payloads(manifest: Manifest) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index, module in enumerate(manifest.modules):
        steps = module.build()
        payloads.append({
            "moduleIndex": index,
            "type": module.type,
            "unsafe": any(step.unsafe for step in steps),
            "capabilities": module.capabilities(),
        })
    return payloads
