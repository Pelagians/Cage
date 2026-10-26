"""Private .app bootstrap, launched by its native host with isolated Python."""
from pathlib import Path
import json
import sys

# -I excludes the checkout, cwd, PYTHONPATH and user site packages.
resources = Path(__file__).resolve().parent
sys.path.insert(0, str(resources / "cage-code"))
from runtime.macos_launch import run_plan, execute


def main():
    config = json.loads((resources / "app-config.json").read_text())
    if config.get("schemaVersion") != "cage.macos-app/v0" or config.get("allowHostAccess") is not True:
        raise ValueError("invalid native application configuration")
    plan = run_plan(resources / "application", store=config["runtimeStore"], state_dir=config["stateParent"],
                    files=sys.argv[1:], allow_host_access=True)
    if plan["identity"] != config["identity"]:
        raise ValueError("packaged application differs from its original state identity; state retained")
    result = execute(plan)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result.get("success") else int(result.get("exitCode") or 1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("Cage application failed: " + str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
