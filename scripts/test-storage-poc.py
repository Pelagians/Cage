#!/usr/bin/env python3
"""Require real completed staging cleanup without changing its retained export."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifact.storage import MARKER, read_json, prune_context, _verify_artifact


def main():
    context = Path(sys.argv[1]).absolute()
    preview = prune_context(context, min_age_hours=0)
    assert preview['eligible'], preview
    artifact = read_json(context / MARKER)['artifact']
    result = prune_context(context, min_age_hours=0, apply=True)
    assert result['removed'] and result['provenanceRetained'], result
    assert read_json(context / MARKER)['status'] == 'cleaned'
    _verify_artifact(artifact, context)
    assert (context / 'export-plan.json').is_file() or (context / 'Containerfile').is_file()
    print(json.dumps({'status': 'passed', 'retainedArtifactVerified': True, 'cleanup': result}, indent=2))


if __name__ == '__main__':
    main()
