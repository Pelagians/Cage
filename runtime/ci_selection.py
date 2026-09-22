"""Select the Cage runtime image matrix from an exact source diff."""

from __future__ import annotations

import argparse
import json
import subprocess

from runtime.catalog import ci_matrix


def select(rows: list[dict[str, str]], paths: list[str]) -> list[dict[str, str]]:
    providers: set[str] = set()
    versions: set[tuple[str, str]] = set()
    for path in paths:
        if path == "container/runtimes/wine/Dockerfile":
            providers.update(("wine", "staging"))
        elif path == "container/runtimes/umu-proton-ge/Dockerfile":
            providers.add("umu-proton-ge")
        elif path in {"tests/smoke-shell-runtime.sh", "container/docker-compose.yml"}:
            versions.update((('wine', '11.0'), ('staging', '11.10')))
        elif path in {"container/build.sh", "container/manager.py"}:
            versions.update((('wine', '11.0'), ('staging', '11.10'), ('umu-proton-ge', 'GE-Proton11-1')))
        else:
            # Shared overlay, catalog, workflows, and unfamiliar paths retain
            # full coverage. A changed path must never silently lose a gate.
            return rows
    return [r for r in rows if r["provider"] in providers or (r["provider"], r["version"]) in versions]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--candidate-provider", default="")
    parser.add_argument("--candidate-version", default="")
    args = parser.parse_args()
    rows = ci_matrix()["include"]
    if args.candidate_provider:
        rows = [r for r in rows if (r["provider"], r["version"]) == (args.candidate_provider, args.candidate_version)]
        if len(rows) != 1:
            raise SystemExit("manual candidate must match exactly one catalog entry")
    elif args.base and set(args.base) != {"0"}:
        paths = subprocess.check_output(
            ["git", "diff", "--name-only", f"{args.base}...{args.head}"], text=True,
        ).splitlines()
        rows = select(rows, paths)
    print(json.dumps({"include": rows}, separators=(",", ":")))


if __name__ == "__main__":
    main()
