"""Source-of-truth documentation assertions for the M3 handoff state."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
D0_HASH = "de01cfb1794790a90e34010198063a8449631e32ec450b8f4368cc21ab7bf6f5"


def test_handoff_records_d0_authorization_and_pr4_merge_state() -> None:
    handoff = (REPO_ROOT / "docs" / "handoff" / "HANDOFF.md").read_text()
    status = (REPO_ROOT / "docs" / "STATUS.md").read_text()

    assert D0_HASH in handoff
    assert "D0 recorded" in handoff
    assert "G1–G6" in handoff and "R1–R7" in handoff
    assert "raw personal material" in handoff
    assert "strict majority" in handoff
    assert "merged in PR #4" in status
    assert "draft PR #4" not in status
    assert "No product code exists yet" not in handoff
