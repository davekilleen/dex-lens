"""Fresh-process contributor controls are reachable from the installed command."""

from __future__ import annotations

from types import SimpleNamespace

from capability_exchange.concierge.cli import main


class _FakeIntake:
    def __init__(self) -> None:
        self.withdrawn: list[str] = []
        self.deleted = 0

    def saved_receipts(self):
        return (("ccr_saved", "submitted-for-review"),)

    def status_saved(self, receipt_id: str):
        assert receipt_id == "ccr_saved"
        return SimpleNamespace(
            receipt_id=receipt_id,
            status="changes-requested",
            manifest_byte_hash="sha256:" + ("a" * 64),
            moderation_reason="Remove the company name.",
        )

    def withdraw_saved(self, receipt_id: str):
        self.withdrawn.append(receipt_id)
        return SimpleNamespace(withdrawn=True)

    def delete_all_saved(self):
        self.deleted += 1
        return SimpleNamespace(
            deleted_count=1,
            retention_disclosure="A minimal abuse-prevention tombstone remains.",
        )


def test_contributions_list_and_status_are_available_after_the_browser_session(
    monkeypatch,
    capsys,
) -> None:
    fake = _FakeIntake()
    monkeypatch.setattr(
        "capability_exchange.contribution.cli._new_intake",
        lambda: fake,
    )

    assert main(["contributions", "list"]) == 0
    assert "ccr_saved" in capsys.readouterr().out
    assert main(["contributions", "status", "ccr_saved"]) == 0
    output = capsys.readouterr().out
    assert "changes-requested" in output
    assert "Remove the company name" in output


def test_withdraw_and_delete_require_an_explicit_yes(
    monkeypatch,
    capsys,
) -> None:
    fake = _FakeIntake()
    monkeypatch.setattr(
        "capability_exchange.contribution.cli._new_intake",
        lambda: fake,
    )

    assert main(["contributions", "withdraw", "ccr_saved"]) == 2
    assert fake.withdrawn == []
    assert "Nothing was changed" in capsys.readouterr().err
    assert main(["contributions", "withdraw", "ccr_saved", "--yes"]) == 0
    assert fake.withdrawn == ["ccr_saved"]

    assert main(["contributions", "delete-all"]) == 2
    assert fake.deleted == 0
    assert main(["contributions", "delete-all", "--yes"]) == 0
    assert fake.deleted == 1
    assert "tombstone" in capsys.readouterr().out
