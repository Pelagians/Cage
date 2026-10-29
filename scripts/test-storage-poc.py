#!/usr/bin/env python3
"""Require real completed staging cleanup without changing its retained export."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifact.storage import MARKER, DISPOSABLE, read_json, prune_context, _verify_artifact, snapshot


def main():
    context = Path(sys.argv[1]).absolute()
    record = read_json(context / MARKER)
    artifact = record['artifact']
    if record['status'] == 'cleaned':
        result = {'removed': record['removed'], 'provenanceRetained': True, 'alreadyCleaned': True}
    else:
        preview = prune_context(context, min_age_hours=0)
        assert preview['eligible'], preview
        result = prune_context(context, min_age_hours=0, apply=True)
    record = read_json(context / MARKER)
    assert result['removed'] and record['status'] == 'cleaned', result
    expected = {name: entry for name, entry in record['entries'].items()
                if Path(name).parts[0] not in DISPOSABLE[record['kind']]}
    assert snapshot(context) == expected, 'retained provenance changed or disposable payload remains'
    _verify_artifact(artifact, context)
    assert (context / 'export-plan.json').is_file() or (context / 'Containerfile').is_file()
    print(json.dumps({'status': 'passed', 'retainedArtifactVerified': True, 'cleanup': result}, indent=2))


if __name__ == '__main__':
    main()
