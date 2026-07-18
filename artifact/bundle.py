"""Cage execution bundle writer."""
from __future__ import annotations
from datetime import datetime, timezone
import json, re
from pathlib import Path
from artifact.graph import build_execution_graph
from builder.pipeline import build_plan
from core.manifest import Manifest
from runtime.providers import resolve_manifest_runtime

STATUS_SCHEMA_VERSION = "cage.bundle-status/v0"
STEP_EVIDENCE_SCHEMA_VERSION = "cage.step-evidence/v0"
STATUS_STATES = {
    "planned",
    "source-failed",
    "build-running",
    "build-failed",
    "build-passed",
    "verification-failed",
    "runnable",
    "run-passed",
}


def bundle_path_for(manifest: Manifest, output_dir: Path) -> Path:
    return output_dir / _safe_name(f"{manifest.name}-{manifest.version}")


def create_bundle(manifest: Manifest, output_dir: Path, *,
                  dry_run: bool) -> Path:
    bundle_path = bundle_path_for(manifest, output_dir)
    if bundle_path.exists():
        raise FileExistsError(bundle_path)
    for rel in ("prefix/drive_c", "runtime", "launch", "metadata",
                "build", "logs"):
        (bundle_path / rel).mkdir(parents=True, exist_ok=False)

    runtime = resolve_manifest_runtime(manifest)
    _write_json(bundle_path / "manifest.cage.json",
                manifest.to_dict())
    _write_json(bundle_path / "runtime/runtime.json",
                runtime.to_dict())
    launch_payload = manifest.launch.to_dict() if manifest.launch else {"hasDefaultLaunch": False}
    if manifest.launch:
        launch_payload["hasDefaultLaunch"] = True
    _write_json(bundle_path / "launch/entrypoint.json",
                launch_payload)
    plan = build_plan(manifest)
    _write_json(bundle_path / "build/build-plan.json",
                {"phases": plan})
    _write_json(bundle_path / "metadata/graph.json",
                build_execution_graph(manifest))

    initial_status = "planned" if dry_run else "build-running"
    _write_status(
        bundle_path,
        state=initial_status,
        dry_run=dry_run,
        runnable=False,
        materialized_prefix=False,
        has_default_launch=manifest.launch is not None,
    )
    _write_step_evidence(
        bundle_path,
        plan,
        attempted=False,
        success=False,
        exit_code=None,
        log_excerpt="dry-run bundle materialized; no build steps executed" if dry_run else "build scheduled; container execution not recorded yet",
    )

    # Provenance differs for dry-run vs. real builds.
    if dry_run:
        notes = [
            "Dry-run bundle records the artifact contract but does "
            "not execute Wine/winetricks installers yet.",
        ]
        (bundle_path / "prefix/drive_c/.keep").write_text(
            "drive_c root placeholder for dry-run bundle\n",
            encoding="utf-8")
        (bundle_path / "logs/build.log").write_text(
            "dry-run bundle materialized; no Wine commands executed\n",
            encoding="utf-8")
    else:
        notes = [
            "Real build — Wine container execution populates the "
            "prefix directory and logs.",
        ]
        (bundle_path / "logs/build.log").write_text(
            "[cage] Build starting — container execution in progress.\n",
            encoding="utf-8")

    _write_json(
        bundle_path / "metadata/provenance.json",
        {
            "schemaVersion": "cage.bundle/v0",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "dryRun": dry_run,
            "builder": "cage-scaffold",
            "manifest": {
                "name": manifest.name,
                "version": manifest.version,
            },
            "runtime": runtime.to_dict(),
            "build": manifest.build.to_dict(),
            "compatibility": manifest.compatibility,
            "declaredProvenance": manifest.provenance,
            "modules": [
                {
                    "moduleIndex": index,
                    "type": module.type,
                    "unsafe": any(step.unsafe for step in module.build()),
                    "capabilities": module.capabilities(),
                }
                for index, module in enumerate(manifest.modules)
            ],
            "notes": notes,
        })

    return bundle_path


def update_bundle_execution_metadata(
    bundle_path: Path,
    *,
    state: str,
    runnable: bool,
    dry_run: bool = False,
    materialized_prefix: bool | None = None,
    has_default_launch: bool | None = None,
    exit_code: int | None = None,
    error: str | None = None,
    log_excerpt: str | None = None,
) -> None:
    """Update status and coarse step evidence after container execution."""
    plan_path = bundle_path / "build" / "build-plan.json"
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    phases = plan_payload.get("phases", [])
    current_status_path = bundle_path / "metadata" / "status.json"
    current_status = (
        json.loads(current_status_path.read_text(encoding="utf-8"))
        if current_status_path.exists()
        else {}
    )
    if materialized_prefix is None:
        materialized_prefix = bool(current_status.get("materializedPrefix", False))
    if has_default_launch is None:
        has_default_launch = bool(current_status.get("hasDefaultLaunch", False))
    success = state in {"build-passed", "runnable", "run-passed"}
    _write_status(
        bundle_path,
        state=state,
        dry_run=dry_run,
        runnable=runnable,
        materialized_prefix=materialized_prefix,
        has_default_launch=has_default_launch,
        exit_code=exit_code,
        error=error,
    )
    _write_step_evidence(
        bundle_path,
        phases,
        attempted=True,
        success=success,
        exit_code=exit_code,
        log_excerpt=log_excerpt,
    )


def _write_status(
    bundle_path: Path,
    *,
    state: str,
    dry_run: bool,
    runnable: bool,
    materialized_prefix: bool | None = None,
    has_default_launch: bool | None = None,
    exit_code: int | None = None,
    error: str | None = None,
) -> None:
    if state not in STATUS_STATES:
        raise ValueError(f"unsupported bundle status state: {state}")
    payload = {
        "schemaVersion": STATUS_SCHEMA_VERSION,
        "state": state,
        "dryRun": dry_run,
        "runnable": runnable,
        "materializedPrefix": materialized_prefix if materialized_prefix is not None else False,
        "hasDefaultLaunch": has_default_launch if has_default_launch is not None else False,
        "exitCode": exit_code,
        "error": error,
    }
    _write_json(bundle_path / "metadata" / "status.json", _drop_none(payload))


def _write_step_evidence(
    bundle_path: Path,
    phases: list[dict[str, object]],
    *,
    attempted: bool,
    success: bool,
    exit_code: int | None,
    log_excerpt: str | None,
) -> None:
    steps = []
    for phase in phases:
        steps.append(_drop_none({
            "id": phase.get("id") or phase.get("phase"),
            "phase": phase.get("phase"),
            "kind": phase.get("kind"),
            "description": phase.get("description"),
            "attempted": attempted,
            "success": success if attempted else False,
            "exitCode": exit_code if attempted else None,
            "logPath": "logs/build.log",
            "logExcerpt": log_excerpt,
        }))
    _write_json(
        bundle_path / "metadata" / "step-evidence.json",
        {
            "schemaVersion": STEP_EVIDENCE_SCHEMA_VERSION,
            "steps": steps,
        },
    )


def _drop_none(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if value is not None}


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-_") or "bundle"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
