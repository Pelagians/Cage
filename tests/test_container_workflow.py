"""Container publication workflow contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manual_container_publication_is_single_row_and_immutable():
    workflow = (ROOT / ".github/workflows/containers.yml").read_text(encoding="utf-8")

    assert "candidate_provider:" in workflow
    assert "candidate_version:" in workflow
    assert 'row["provider"] == os.environ["CANDIDATE_PROVIDER"]' in workflow
    assert 'row["version"] == os.environ["CANDIDATE_VERSION"]' in workflow
    assert "expected exactly one candidate row" in workflow
    assert (
        "github.event_name != 'workflow_dispatch' && matrix.published_ref || ''"
        in workflow
    )
    assert (
        "github.event_name != 'workflow_dispatch' && matrix.published_alias_refs || ''"
        in workflow
    )
    assert "${{ github.sha }}-${{ matrix.tag }}" in workflow
