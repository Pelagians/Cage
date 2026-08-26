"""Container-executor for real Cage builds.

Runs the Cage build pipeline inside a Cage Wine/Proton OCI
container, producing a real built prefix with installed dependencies
and applications.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os, queue, re, shutil, subprocess, sys, tempfile, threading, time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artifact.bundle import update_bundle_execution_metadata
from artifact.inspection import verify_bundle, verify_prefix_materialization
from core.chocolatey.assets import load_asset_bytes
from builder.pipeline import generate_build_script
from core.manifest import Manifest
from runtime.providers import required_cfw_runtime_artifact, required_cfw_runtime_image, resolve_manifest_runtime, resolve_runtime
from runtime.runner_cache import ensure_runner


@dataclass
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


def _run_container_command(cmd: list[str], *, timeout: int) -> _CommandResult:
    """Run a container command while streaming combined output to stderr.

    The CLI's stdout is reserved for machine-readable JSON. Progress therefore
    streams to stderr and is also returned so the caller can persist build.log.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("container process did not expose stdout")

    lines: list[str] = []
    output_queue: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout:
                output_queue.put(line)
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    stream_done = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.kill()
            output = "".join(lines)
            raise subprocess.TimeoutExpired(cmd, timeout, output=output)

        try:
            item = output_queue.get(timeout=min(0.2, remaining))
        except queue.Empty:
            item = "__CAGE_NO_OUTPUT__"

        if item is None:
            stream_done = True
        elif item != "__CAGE_NO_OUTPUT__":
            lines.append(item)
            print(item, end="", file=sys.stderr, flush=True)

        if stream_done and proc.poll() is not None:
            break

    return _CommandResult(proc.returncode or 0, "".join(lines), "")


@dataclass
class BuildResult:
    """Result of a real container-executed Cage build."""

    success: bool
    bundle_path: str
    runtime_provider: str
    runtime_version: str
    image_ref: str
    engine: str
    runnable: bool = False
    exit_code: int | None = None
    log: str = ""
    prefix_size: int | None = None
    prefix_file_count: int | None = None
    error: str | None = None
    runner_cache: dict[str, Any] | None = None
    module_cache: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "runnable": self.runnable,
            "bundlePath": self.bundle_path,
            "runtimeProvider": self.runtime_provider,
            "runtimeVersion": self.runtime_version,
            "imageRef": self.image_ref,
            "engine": self.engine,
            "exitCode": self.exit_code,
            "prefixSize": self.prefix_size,
            "prefixFileCount": self.prefix_file_count,
            "error": self.error,
            "runnerCache": self.runner_cache,
            "moduleCache": self.module_cache,
        }


def _find_engine(prefer: str | None = None) -> str:
    """Return 'docker' or 'podman' depending on what's available.

    If *prefer* is given, checks that specific engine first.
    """
    candidates = [prefer] if prefer else []
    candidates.extend(e for e in ("docker", "podman") if e != prefer)
    for cmd in candidates:
        path = shutil.which(cmd)
        if path is not None:
            if cmd == "docker":
                # Podman 5+ ships a Docker CLI emulation binary. Detect it
                # so SELinux mount labels (':z') are applied correctly.
                try:
                    r = subprocess.run(
                        [path, "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if "podman" in r.stdout.lower():
                        return "podman"
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
            return cmd
    msg = "No container engine found. Install Docker or Podman, or use --dry-run."
    raise RuntimeError(msg)


def _check_image(image_ref: str, engine: str) -> bool:
    """Return True if *image_ref* exists locally."""
    try:
        r = subprocess.run(
            [engine, "image", "inspect", image_ref],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _pull_image(image_ref: str, engine: str) -> bool:
    """Attempt to pull *image_ref*. Returns True on success."""
    try:
        r = subprocess.run(
            [engine, "pull", image_ref],
            capture_output=True, text=True, timeout=180,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _resolve_image_ref(manifest: Manifest, engine: str) -> str | None:
    """Resolve the OCI image reference for this manifest's runtime.

    Resolution is catalog-backed:
      1. Prefer a local developer image if it exists.
      2. Pull the published GHCR tag so mutable catalog tags such as
         ghcr.io/pelagians/cage-wine:11.0 refresh after CI rebuilds.
      3. Fall back to an already-local published tag when offline.
    Returns the image ref, or None if unresolvable.
    """
    binding = resolve_runtime(manifest.runtime)

    # Local developer images are explicit overrides and should keep working
    # without network access.
    if binding.local_oci_image and _check_image(binding.local_oci_image, engine):
        return binding.local_oci_image

    # Published catalog tags are mutable: CI can rebuild the same runtime tag
    # after Dockerfile changes. Pull before trusting a cached local copy so
    # machines don't keep running stale images missing newly added tooling.
    if binding.oci_image:
        if _pull_image(binding.oci_image, engine):
            return binding.oci_image
        if _check_image(binding.oci_image, engine):
            return binding.oci_image
    return None


RUNNER_CONTAINER_DIR = "/opt/cage-runner"
MODULE_CACHE_CONTAINER_DIR = "/opt/cage-module-cache"


_required_cfw_runtime_image = required_cfw_runtime_image


def _volume_mount(source: Path | str, target: str, *, engine: str, read_only: bool = False) -> str:
    """Return a Docker/Podman bind mount string.

    Rootless Podman on SELinux-enforcing hosts needs an SELinux label option
    for bind-mounted source trees, otherwise scripts such as
    /opt/cage/build/run.sh can exist but be unreadable inside the
    container ("Permission denied"). Use the shared label so the same bundle,
    workspace, and runner cache can be reused by build and run containers.
    """
    options: list[str] = []
    if read_only:
        options.append("ro")
    if engine == "podman":
        options.append("z")
    suffix = f":{','.join(options)}" if options else ""
    return f"{Path(source).resolve()}:{target}{suffix}"


def _prepare_runner_cache(manifest: Manifest, cache_dir: Path | str | None, *, engine: str) -> dict[str, Any] | None:
    runner_id = manifest.runtime.runner
    if not runner_id:
        return None
    result = ensure_runner(runner_id, cache_dir=Path(cache_dir) if cache_dir else None)
    runner_dir = Path(str(result["runnerDir"])).resolve()
    payload = dict(result)
    payload.update({
        "runnerId": runner_id,
        "containerDir": RUNNER_CONTAINER_DIR,
        "containerBin": f"{RUNNER_CONTAINER_DIR}/bin",
        "mount": _volume_mount(runner_dir, RUNNER_CONTAINER_DIR, engine=engine, read_only=True),
        "environment": {
            "CAGE_RUNNER_ID": runner_id,
            "CAGE_RUNNER_BIN": f"{RUNNER_CONTAINER_DIR}/bin",
        },
    })
    return payload


def _prepare_module_cache(cache_dir: Path | str | None, *, engine: str) -> dict[str, Any] | None:
    if cache_dir is None:
        return None
    module_cache_dir = Path(cache_dir).resolve()
    module_cache_dir.mkdir(parents=True, exist_ok=True)
    return {
        "cacheDir": str(module_cache_dir),
        "containerDir": MODULE_CACHE_CONTAINER_DIR,
        "mount": _volume_mount(module_cache_dir, MODULE_CACHE_CONTAINER_DIR, engine=engine),
        "environment": {
            "CAGE_MODULE_CACHE_DIR": MODULE_CACHE_CONTAINER_DIR,
        },
    }


_CHOCOLATEY_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$")
_ATOM_NS = "http://www.w3.org/2005/Atom"
_ODATA_DATA_NS = "http://schemas.microsoft.com/ado/2007/08/dataservices"


def _resolve_public_chocolatey_package_receipt(
    source_url: str, package_id: str, version: str | None = None
) -> dict[str, str] | None:
    if source_url != "https://community.chocolatey.org/api/v2/":
        return None

    def fetch(path: str, query: dict[str, str]) -> ET.Element | None:
        request = urllib.request.Request(
            source_url.rstrip("/") + path + "?" + urllib.parse.urlencode(query),
            headers={
                "Accept": "application/atom+xml,application/xml",
                "User-Agent": "Cage/0.1 package-receipt",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read(2_000_000)
            return ET.fromstring(payload)
        except (OSError, ET.ParseError, ValueError):
            return None

    if version is not None:
        if _CHOCOLATEY_VERSION_RE.fullmatch(version) is None:
            return None
        primary = fetch(
            f"/Packages(Id='{package_id}',Version='{version}')", {}
        )
    else:
        primary = fetch("/Packages()", {
            "$filter": f"Id eq '{package_id}' and IsLatestVersion",
            "$select": "Id,Version,IsLatestVersion,PackageHash,PackageHashAlgorithm",
        })
    if primary is None:
        return None
    if version is not None:
        exact_title = _feed_exact_value(primary, "title", namespace=_ATOM_NS)
        exact_version = _feed_exact_value(primary, "Version", namespace=_ODATA_DATA_NS)
        if (
            primary.tag != f"{{{_ATOM_NS}}}entry"
            or exact_title is None
            or exact_title.casefold() != package_id.casefold()
            or exact_version != version
        ):
            return None
        entries = [primary]
    else:
        if primary.tag != "{http://www.w3.org/2005/Atom}feed":
            return None
        primary_entries = [
            node for node in primary
            if node.tag.rsplit("}", 1)[-1] == "entry"
        ]
        primary_matches = _matching_feed_entries(primary, package_id)
        if primary_entries:
            if len(primary_matches) != len(primary_entries):
                return None
            entries = [
                entry for entry in primary_matches
                if _feed_value(entry, "IsLatestVersion").casefold() == "true"
            ]
            if len(entries) != 1:
                return None
        else:
            root = fetch("/Search()", {
                "searchTerm": f"'{package_id}'",
                "targetFramework": "''",
                "includePrerelease": "false",
                "$skip": "0",
                "$top": "50",
            })
            entries = _matching_feed_entries(root, package_id) if root is not None else []
            entries = [entry for entry in entries if _feed_value(entry, "IsLatestVersion").casefold() == "true"]
    if len(entries) != 1:
        return None
    node = entries[0]
    if version is not None:
        authority_fields = {
            name: _feed_exact_value(node, name, namespace=_ODATA_DATA_NS)
            for name in ("Version", "PackageHash", "PackageHashAlgorithm")
        }
        if any(value is None for value in authority_fields.values()):
            return None
        values = {name: value or "" for name, value in authority_fields.items()}
    else:
        values = {
            name: _feed_value(node, name, namespace=_ODATA_DATA_NS)
            for name in ("Version", "PackageHash", "PackageHashAlgorithm")
        }
    if values["PackageHashAlgorithm"].upper() != "SHA512" or not values["Version"]:
        return None
    try:
        package_hash = base64.b64decode(values["PackageHash"], validate=True).hex()
    except (KeyError, ValueError):
        return None
    if len(package_hash) != 128:
        return None
    return {
        "version": values["Version"],
        "packageHashAlgorithm": "SHA512",
        "packageHash": package_hash,
    }


def _feed_exact_value(node: ET.Element, name: str, *, namespace: str) -> str | None:
    expected = f"{{{namespace}}}{name}"
    same_local_name = [
        child
        for child in node.iter()
        if child.tag.rsplit("}", 1)[-1] == name
    ]
    if len(same_local_name) != 1 or same_local_name[0].tag != expected:
        return None
    text = same_local_name[0].text
    return text.strip() if text else ""


def _feed_value(node: ET.Element, name: str, *, namespace: str | None = None) -> str:
    expected = f"{{{namespace}}}{name}" if namespace is not None else None
    return next(
        (
            child.text.strip()
            for child in node.iter()
            if child.text
            and (child.tag == expected if expected is not None else child.tag.rsplit("}", 1)[-1] == name)
        ),
        "",
    )


def _matching_feed_entries(root: ET.Element, package_id: str) -> list[ET.Element]:
    entries: list[ET.Element] = []
    for node in root:
        if node.tag.rsplit("}", 1)[-1] != "entry":
            continue
        if _feed_value(node, "title").casefold() == package_id.casefold():
            entries.append(node)
    return entries


def _has_symlink_ancestor(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _has_symlink_component(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    if current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _safe_package_tree(lib: Path, package_id: str) -> bool:
    try:
        matches = [
            child for child in lib.iterdir()
            if child.name.casefold() == package_id.casefold()
        ]
        if len(matches) != 1 or matches[0].is_symlink() or not matches[0].is_dir():
            return False
        stack = [matches[0]]
        while stack:
            directory = stack.pop()
            for child in directory.iterdir():
                if child.is_symlink():
                    return False
                if child.is_dir():
                    stack.append(child)
        return True
    except OSError:
        return False


def _write_host_chocolatey_package_evidence(manifest: Manifest, bundle_path: Path) -> bool:
    modules = [module for module in manifest.modules if getattr(module, "type", None) == "chocolatey"]
    if not modules:
        return True
    if len(modules) != 1:
        return False
    module = modules[0]
    install = getattr(module, "install", None)
    packages = install.get("packages") if isinstance(install, dict) else None
    if not isinstance(packages, list) or not all(isinstance(package, str) for package in packages):
        return False
    if not packages:
        return True
    source_url = getattr(module, "package_source", None) or "https://community.chocolatey.org/api/v2/"
    bundle_root = bundle_path.resolve()
    if _has_symlink_ancestor(bundle_path):
        return False
    lib = bundle_path / "prefix/drive_c/ProgramData/chocolatey/lib"
    output = bundle_path / "metadata/chocolatey-package-evidence.json"
    if _has_symlink_component(lib, bundle_path) or output.is_symlink() or _has_symlink_component(output.parent, bundle_path):
        return False
    try:
        lib.resolve().relative_to(bundle_root)
        output.parent.resolve().relative_to(bundle_root)
    except (OSError, ValueError):
        return False
    if not all(_safe_package_tree(lib, package) for package in packages):
        return False
    with tempfile.TemporaryDirectory(prefix="cage-package-evidence-") as temporary:
        helper = Path(temporary) / "package-evidence.py"
        helper.write_bytes(load_asset_bytes("package-evidence.py"))
        result = subprocess.run(
            [
                sys.executable, str(helper), "--lib", str(lib), "--output", str(output),
                "--requested", json.dumps(packages, separators=(",", ":")),
                "--install-rc", "0", "--settle-rc", "0", "--source-url", source_url,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        return False
    try:
        evidence = json.loads(output.read_text(encoding="utf-8"))
        observed = {item["id"]: item for item in evidence["requested"]}
        for package in packages:
            item = observed.get(package)
            if not isinstance(item, dict) or not isinstance(item.get("version"), str):
                return False
            receipt = _resolve_public_chocolatey_package_receipt(
                source_url, package, item["version"]
            )
            if receipt is None:
                return False
            nupkg_path = lib / item["nupkgPath"] if isinstance(item, dict) else None
            if nupkg_path is not None and (
                _has_symlink_component(nupkg_path, lib)
                or not nupkg_path.resolve().is_relative_to(lib.resolve())
            ):
                return False
            if (
                not isinstance(item, dict)
                or item.get("version") != receipt["version"]
                or nupkg_path is None
                or not nupkg_path.is_file()
                or nupkg_path.is_symlink()
                or hashlib.sha512(nupkg_path.read_bytes()).hexdigest() != receipt["packageHash"]
            ):
                return False
            item["feedReceipt"] = receipt
            item["authority"] = "host-resolved-public-feed-receipt"
        evidence["authority"] = "host-resolved-public-feed-receipt"
        if output.is_symlink() or _has_symlink_component(output.parent, bundle_path):
            return False
        temporary_output = output.with_name(output.name + ".host.tmp")
        if temporary_output.exists() or temporary_output.is_symlink():
            return False
        with temporary_output.open("x", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary_output.replace(output)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return True


# ---------------------------------------------------------------------------
# Container execution
# ---------------------------------------------------------------------------

def execute_inside_container(
    manifest: Manifest,
    bundle_path: Path,
    *,
    engine: str | None = None,
    image_ref: str | None = None,
    timeout: int = 7200,
    workspace: Path | str | None = None,
    runner_cache_dir: Path | str | None = None,
    module_cache_dir: Path | str | None = None,
    stop_before: str | None = None,
) -> BuildResult:
    """Run the Cage build inside the runtime provider's Docker/Podman container.

    Args:
        manifest:         The parsed Cage manifest.
        bundle_path:      Host-path to the bundle output directory (must exist).
        engine:           Container engine (docker, podman). Auto-detect if None.
        image_ref:        Explicit OCI image reference. Resolve from manifest if None.
        timeout:          Max seconds for the entire build.
        workspace:        Host workspace mounted read-only at /workspace.
        runner_cache_dir: Optional runner cache root for runtime.runner archives.
        module_cache_dir: Optional cache root for module payload archives.
        stop_before: Optional phase boundary for checkpoint prep, currently install-apps.

    Returns:
        BuildResult with success/failure and metadata.
    """
    engine = _find_engine(engine) if engine == "docker" else (engine or _find_engine())
    runtime = resolve_manifest_runtime(manifest)

    # Resolve image reference. A CFW prepared runtime binds the build to the
    # exact producer image digest; explicit caller overrides may not replace it.
    required_cfw_artifact = required_cfw_runtime_artifact(manifest)
    if required_cfw_artifact is not None and required_cfw_artifact.get("sessionContract") != "cage.selkies-wayland/v1":
        raise RuntimeError(
            "CFW runtime is not a universal Selkies Cage image; publish and pin a qualified producer runtime"
        )
    required_cfw_image = required_cfw_runtime_image(manifest)
    if required_cfw_image and manifest.runtime.runner:
        raise RuntimeError("CFW prepared runtimes cannot use runtime.runner; the producer image owns Wine identity")
    if image_ref and required_cfw_image and image_ref != required_cfw_image:
        raise RuntimeError(
            f"requested runtime image {image_ref} does not match pinned CFW image {required_cfw_image}"
        )
    img = image_ref or required_cfw_image or _resolve_image_ref(manifest, engine)
    if not img:
        # Fallback: construct a ref for the user's information
        from container.manager import get_image_ref as _img_ref
        img = _img_ref(manifest.runtime.provider, manifest.runtime.version)

    # ---- Resolve optional downloadable runner cache and module payload cache ----
    runner_cache = _prepare_runner_cache(manifest, runner_cache_dir, engine=engine)
    module_cache = _prepare_module_cache(module_cache_dir, engine=engine)

    # ---- Write the build script into the bundle ----
    script_path = bundle_path / "build" / "run.sh"
    script = generate_build_script(
        manifest,
        bundle_mount="/opt/cage",
        workspace_mount="/workspace",
        timeout_per_phase=timeout,
    )
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    # ---- Ensure logs dir exists ----
    (bundle_path / "logs").mkdir(parents=True, exist_ok=True)

    # ---- Determine mount points ----
    # Bundle:       /host/bundle-name → /opt/cage (inside container)
    # Workspace:     selected workspace → /workspace       (for source-file access)
    host_bundle = bundle_path.resolve()
    host_workspace = Path(workspace or Path.cwd()).resolve()
    mounts = [
        _volume_mount(host_bundle, "/opt/cage", engine=engine),
        _volume_mount(host_workspace, "/workspace", engine=engine, read_only=True),
    ]
    build_wrapper = "set -euo pipefail\nexec bash /opt/cage/build/run.sh\n"
    environment: dict[str, str] = {
        "CAGE_RUNTIME_IMAGE": img,
        "PUID": str(os.getuid()),
        "PGID": str(os.getgid()),
        "CAGE_BUILD_SCRIPT_B64": base64.b64encode(build_wrapper.encode("utf-8")).decode("ascii"),
        "CAGE_SESSION_MODE": "build",
        "CAGE_WINE_GRAPHICS": "xwayland",
        "CAGE_EXIT_WHEN_DONE": "true",
        "START_DOCKER": "false",
        "PIXELFLUX_WAYLAND": "true",
        "RESTART_APP": "false",
    }
    environment.update(runtime.environment or {})
    if runner_cache:
        mounts.append(runner_cache["mount"])
        environment.update(runner_cache["environment"])
    if module_cache:
        mounts.append(module_cache["mount"])
        environment.update(module_cache["environment"])

    # ---- Build the docker/podman run command ----
    cmd = [
        engine, "run", "--rm",
    ]
    build_network = getattr(getattr(manifest, "build", None), "network", "none") or "none"
    if build_network != "none":
        cmd.extend(["--net", build_network])
    for m in mounts:
        cmd.extend(["-v", m])
    for key, value in environment.items():
        cmd.extend(["-e", f"{key}={value}"])
    # Ensure shared memory is large enough for Wine
    cmd.extend(["--shm-size", "2g"])
    # Preserve the universal image's inherited LinuxServer /init. The Labwc
    # autostart consumes CAGE_BUILD_SCRIPT_B64 and records the real task code.
    cmd.append(img)

    # ---- Execute ----
    log_lines: list[str] = []
    log_lines.append(f"[cage] Engine: {engine}")
    log_lines.append(f"[cage] Image:  {img}")
    log_lines.append(f"[cage] Bundle: {host_bundle}")
    log_lines.append(f"[cage] CWD:    {host_workspace}")
    if runner_cache:
        log_lines.append(f"[cage] Runner: {runner_cache['runnerId']} mounted at {runner_cache['containerDir']}")
    if module_cache:
        log_lines.append(f"[cage] Module cache: {module_cache['cacheDir']} mounted at {module_cache['containerDir']}")
    log_lines.append("")

    try:
        for line in log_lines:
            print(line, file=sys.stderr, flush=True)
        result = _run_container_command(cmd, timeout=timeout)
        log_lines.append(result.stdout or "")
        if result.stderr:
            log_lines.append("--- stderr ---")

        log_text = "\n".join(log_lines)
        (bundle_path / "logs" / "build.log").write_text(log_text, encoding="utf-8")

        status_receipt = bundle_path / "logs" / "container-exit-code"
        if status_receipt.is_file():
            try:
                exit_code = int(status_receipt.read_text(encoding="utf-8").strip())
            except ValueError:
                exit_code = result.returncode
            status_receipt.unlink(missing_ok=True)
        else:
            exit_code = result.returncode
        container_success = exit_code == 0
        prefix_size = None
        prefix_file_count = None
        runnable = False
        error: str | None = None

        if not container_success:
            success = False
            state = "build-failed"
            error = f"container exited with code {exit_code}"
            materialized_prefix = False
        else:
            host_evidence_ok = _write_host_chocolatey_package_evidence(manifest, bundle_path)
            prefix_verification = verify_prefix_materialization(bundle_path)
            checks = list(prefix_verification.get("checks") or [])
            has_default_launch = manifest.launch is not None
            failed_checks = [
                check for check in checks
                if check.get("ok") is not True
                and (check.get("id") != "launch-executable" or has_default_launch)
            ]
            if not host_evidence_ok:
                failed_checks.append({
                    "id": "host-chocolatey-package-evidence",
                    "ok": False,
                    "message": "host failed to bind requested packages to exported nuspec and nupkg bytes",
                })
            materialized_prefix = prefix_verification.get("materialized") is True
            prefix_size = int(prefix_verification.get("byteSize") or 0)
            prefix_file_count = int(prefix_verification.get("fileCount") or 0)
            success = not failed_checks
            runnable = success and has_default_launch
            state = "runnable" if runnable else "build-passed" if success else "verification-failed"
            if failed_checks:
                reasons = "; ".join(str(check.get("message")) for check in failed_checks)
                error = f"materialized prefix verification failed: {reasons}"

        update_bundle_execution_metadata(
            bundle_path,
            state=state,
            runnable=runnable,
            materialized_prefix=materialized_prefix,
            has_default_launch=manifest.launch is not None,
            exit_code=exit_code,
            error=error,
            log_excerpt=(log_text[-1000:] if log_text else None),
        )

        if runnable:
            bundle_verification = verify_bundle(bundle_path)
            if not bundle_verification.get("runnable"):
                success = False
                runnable = False
                state = "verification-failed"
                error = "bundle verification rejected the materialized prefix"
                update_bundle_execution_metadata(
                    bundle_path,
                    state=state,
                    runnable=False,
                    materialized_prefix=materialized_prefix,
                    has_default_launch=True,
                    exit_code=exit_code,
                    error=error,
                    log_excerpt=(log_text[-1000:] if log_text else None),
                )

        return BuildResult(
            success=success,
            runnable=runnable,
            bundle_path=str(host_bundle),
            runtime_provider=manifest.runtime.provider,
            runtime_version=manifest.runtime.version,
            image_ref=img,
            engine=engine,
            exit_code=exit_code,
            log=log_text,
            prefix_size=prefix_size,
            prefix_file_count=prefix_file_count,
            error=error,
            runner_cache=runner_cache,
            module_cache=module_cache,
        )

    except FileNotFoundError:
        error = (f"Container engine '{engine}' not found. "
                 "Install Docker or Podman, or use --dry-run to skip execution.")
        log_lines.append(error)
        log_text = "\n".join(log_lines)
        (bundle_path / "logs" / "build.log").write_text(log_text, encoding="utf-8")
        update_bundle_execution_metadata(
            bundle_path,
            state="build-failed",
            runnable=False,
            error=error,
            log_excerpt=(log_text[-1000:] if log_text else None),
        )
        return BuildResult(
            success=False, bundle_path=str(host_bundle),
            runtime_provider=manifest.runtime.provider,
            runtime_version=manifest.runtime.version,
            image_ref=img, engine=engine,
            error=error,
            runner_cache=runner_cache,
            module_cache=module_cache,
        )

    except subprocess.TimeoutExpired as exc:
        if exc.output:
            output = exc.output.decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else str(exc.output)
            log_lines.append(output)
        error = f"Build timed out after {timeout}s."
        log_lines.append(error)
        log_text = "\n".join(log_lines)
        (bundle_path / "logs" / "build.log").write_text(log_text, encoding="utf-8")
        update_bundle_execution_metadata(
            bundle_path,
            state="build-failed",
            runnable=False,
            error=error,
            log_excerpt=(log_text[-1000:] if log_text else None),
        )
        return BuildResult(
            success=False, bundle_path=str(host_bundle),
            runtime_provider=manifest.runtime.provider,
            runtime_version=manifest.runtime.version,
            image_ref=img, engine=engine,
            error=error,
            runner_cache=runner_cache,
            module_cache=module_cache,
        )

    except subprocess.CalledProcessError as exc:
        error = f"Container exited with code {exc.returncode}: {exc.stderr[-500:] if exc.stderr else '(no stderr)'}"
        log_lines.append(exc.stdout or "")
        log_lines.append(exc.stderr or "")
        log_text = "\n".join(log_lines)
        (bundle_path / "logs" / "build.log").write_text(log_text, encoding="utf-8")
        update_bundle_execution_metadata(
            bundle_path,
            state="build-failed",
            runnable=False,
            exit_code=exc.returncode,
            error=error,
            log_excerpt=(log_text[-1000:] if log_text else None),
        )
        return BuildResult(
            success=False, bundle_path=str(host_bundle),
            runtime_provider=manifest.runtime.provider,
            runtime_version=manifest.runtime.version,
            image_ref=img, engine=engine,
            exit_code=exc.returncode,
            error=error,
            runner_cache=runner_cache,
            module_cache=module_cache,
        )

    except RuntimeError as exc:
        error = str(exc)
        log_lines.append(error)
        log_text = "\n".join(log_lines)
        (bundle_path / "logs" / "build.log").write_text(log_text, encoding="utf-8")
        update_bundle_execution_metadata(
            bundle_path,
            state="build-failed",
            runnable=False,
            error=error,
            log_excerpt=(log_text[-1000:] if log_text else None),
        )
        return BuildResult(
            success=False, bundle_path=str(host_bundle),
            runtime_provider=manifest.runtime.provider,
            runtime_version=manifest.runtime.version,
            image_ref=img or "", engine=engine,
            error=error,
            runner_cache=runner_cache,
            module_cache=module_cache,
        )


__all__ = [
    "BuildResult",
    "execute_inside_container",
    "_check_image",
    "_pull_image",
    "_find_engine",
    "_prepare_runner_cache",
    "_prepare_module_cache",
    "_run_container_command",
]
