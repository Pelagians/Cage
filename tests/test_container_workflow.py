"""Container publication workflow contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manual_container_publication_is_single_row_and_immutable():
    workflow = (ROOT / ".github/workflows/containers.yml").read_text(encoding="utf-8")

    assert "candidate_provider:" in workflow
    assert "candidate_version:" in workflow
    assert "--candidate-provider \"$CANDIDATE_PROVIDER\"" in workflow
    assert "--candidate-version \"$CANDIDATE_VERSION\"" in workflow
    assert "manual candidate must match exactly one catalog entry" in (
        ROOT / "runtime/ci_selection.py"
    ).read_text(encoding="utf-8")
    assert "candidate-{2}-{3}-{4}" in workflow
    assert "if: github.event_name == 'push'" in workflow
    assert 'docker buildx imagetools create "${tags[@]}" "$IMAGE_UNDER_TEST"' in workflow
