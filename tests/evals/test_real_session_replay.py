from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tests.evals.real_session_fixture import (
    CANARY,
    EXPECTED_COUNTS,
    real_session_fingerprint,
    real_session_input,
    real_session_ledger,
    real_session_report,
    synthetic_entry_ids,
)

from capability_exchange.evaluation.diagnosis import evaluate_diagnosis

EXPECTED = Path(__file__).parents[1] / "fixtures" / "evals" / "real-session-expected.json"


def expected_contract() -> dict[str, object]:
    raw = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise TypeError("real-session expected contract must be a string-keyed mapping")
    return raw


def test_report_cannot_claim_93_covered_when_80_are_not_assessed() -> None:
    ledger = real_session_ledger()
    report = real_session_report().replace(
        "80 capabilities remain Unknown",
        "93 capabilities are already covered",
    )
    expected = expected_contract()

    assert synthetic_entry_ids() == tuple(
        f"invented-capability-{index:03d}" for index in range(115)
    )
    assert Counter(item.disposition for item in ledger.entries) == EXPECTED_COUNTS
    assert expected["catalogue_entry_count"] == len(ledger.entries)
    assert expected["disposition_counts"] == {
        disposition.value: count for disposition, count in EXPECTED_COUNTS.items()
    }
    assert {item.source_class for item in real_session_input().sources} == set(
        expected["required_provenance_classes"]
    )
    assert len({item.name for item in real_session_input().sources}) == 1
    assert all(
        reference.startswith(("probe-token:", "file-token:"))
        for item in ledger.entries
        for reference in item.evidence_references
    )
    assert all(
        item.evidence.reference.startswith(("probe-token:", "file-token:"))
        for item in real_session_fingerprint().observations
    )
    retained = "\n".join(
        (
            real_session_fingerprint().model_dump_json(),
            ledger.model_dump_json(),
            report,
            json.dumps(expected),
        )
    )
    assert CANARY not in retained

    result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=report,
        expected=expected,
    )

    assert not result.passed
    assert any("ledger-derived facts" in item for item in result.report_errors), (
        result.report_errors
    )
