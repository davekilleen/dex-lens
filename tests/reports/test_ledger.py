from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import NOW, sign_envelope, unsigned_envelope

from capability_exchange.catalogue.agent import render_catalogue_ledger_template
from capability_exchange.catalogue.v2 import KeyRing, verify_catalogue_envelope
from capability_exchange.diagnosis.comparison import ComparisonLedger
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    HealthState,
    RuntimeState,
)
from capability_exchange.diagnosis.report import canonical_ledger_digest
from capability_exchange.reports import cli
from capability_exchange.reports.ledger import load_and_validate_ledger


def _verified_catalogue():
    signing_key = Ed25519PrivateKey.from_private_bytes(
        b"reports-ledger-test-key".ljust(32, b"!")
    )
    public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    keyring = KeyRing({"reports-ledger-test": base64.b64encode(public_key).decode("ascii")})
    raw = sign_envelope(
        unsigned_envelope(version=5, key_id="reports-ledger-test"), signing_key
    )
    return verify_catalogue_envelope(raw, keyring=keyring, now=NOW)


def test_complete_ledger_is_bound_to_the_exact_verified_catalogue(tmp_path: Path) -> None:
    verified = _verified_catalogue()
    path = tmp_path / "ledger.json"
    path.write_text(render_catalogue_ledger_template(verified), encoding="utf-8")

    ledger, problems = load_and_validate_ledger(path, verified)

    assert problems == []
    assert ledger is not None
    assert {item.catalogue_id for item in ledger.entries} == {
        item.capability_id for item in verified.catalogue.capabilities
    }


def test_ledger_for_another_catalogue_is_refused(tmp_path: Path) -> None:
    verified = _verified_catalogue()
    payload = json.loads(render_catalogue_ledger_template(verified))
    payload["catalogue_sha256"] = "0" * 64
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    ledger, problems = load_and_validate_ledger(path, verified)

    assert ledger is None
    assert any("exact verified catalogue" in problem for problem in problems)


def test_ledger_missing_one_catalogue_entry_is_refused(tmp_path: Path) -> None:
    verified = _verified_catalogue()
    payload = json.loads(render_catalogue_ledger_template(verified))
    payload["entries"] = []
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    ledger, problems = load_and_validate_ledger(path, verified)

    assert ledger is None
    assert any("ledger" in problem.lower() for problem in problems)


def test_revalidation_preserves_stored_local_rows(tmp_path: Path) -> None:
    verified = _verified_catalogue()
    payload = json.loads(render_catalogue_ledger_template(verified))
    payload["local_entries"] = [
        {
            "observation_id": "observation:sha256:" + "a" * 64,
            "kind": "skill",
            "identity": "invented-local-skill",
            "configuration_state": ConfigurationState.IMPLEMENTED.value,
            "runtime_state": RuntimeState.RECENTLY_RUN.value,
            "health_state": HealthState.BROKEN.value,
            "disposition": "not-assessed",
            "mapped_catalogue_ids": [],
            "mapped_capability_ids": [],
            "evidence_references": [],
            "reason": "Not assessed.",
            "limitation": "No local comparison was made.",
        }
    ]
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    ledger, problems = load_and_validate_ledger(path, verified)

    assert problems == []
    assert ledger is not None
    assert len(ledger.local_entries) == 1
    assert ledger.local_entries[0].runtime_state is RuntimeState.RECENTLY_RUN
    assert ledger.local_entries[0].health_state is HealthState.BROKEN


def test_canonical_json_rebind_preserves_rankings_and_digest(tmp_path: Path) -> None:
    verified = _verified_catalogue()
    payload = json.loads(render_catalogue_ledger_template(verified))
    catalogue_id = verified.catalogue.capabilities[0].capability_id
    evidence_id = "file-token:ranked-recommendation.md"
    payload["capabilities"] = [
        {
            "capability_id": "human-memory",
            "title": "Remember important context",
            "job_ids": ["remember-what-matters"],
            "catalogue_ids": [catalogue_id],
            "person_observation_ids": [],
        }
    ]
    payload["entries"] = [
        {
            "catalogue_id": catalogue_id,
            "disposition": "worth-borrowing",
            "capability_id": "human-memory",
            "evidence_references": [evidence_id],
            "method_compared": True,
            "reason": "The capability addresses a grounded memory gap.",
        }
    ]
    payload["ranked_recommendations"] = [
        {
            "catalogue_id": catalogue_id,
            "capability_id": "human-memory",
            "factors": {
                "reliability_risk": 3,
                "job_relevance": 2,
                "workflow_leverage": 2,
                "evidence_strength": 2,
                "adoption_effort": 1,
            },
            "evidence_ids": [evidence_id],
            "observation_ids": [],
            "reason": "The capability addresses a grounded memory gap.",
            "rank": 1,
        }
    ]
    source = ComparisonLedger.model_validate(payload)
    expected_digest = canonical_ledger_digest(source)
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    rebound, problems = load_and_validate_ledger(path, verified)

    assert problems == []
    assert rebound is not None
    assert rebound.ranked_recommendations == source.ranked_recommendations
    assert canonical_ledger_digest(rebound) == expected_digest


def test_report_command_requires_a_ledger() -> None:
    ledger, problems = cli._ledger_gate(None)

    assert ledger is None
    assert any("--ledger" in problem for problem in problems)
