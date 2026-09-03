from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import NOW, sign_envelope, unsigned_envelope

from capability_exchange.catalogue.agent import render_catalogue_ledger_template
from capability_exchange.catalogue.v2 import (
    KeyRing,
    VerifiedCatalogueStore,
    verify_catalogue_envelope,
)
from capability_exchange.diagnosis.comparison import (
    ComparisonLedger,
    Disposition,
    GroundedInsight,
    InsightKind,
)
from capability_exchange.diagnosis.expectations import (
    ExpectationState,
    SignificantExpectation,
)
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    HealthState,
    RuntimeState,
)
from capability_exchange.diagnosis.report import (
    canonical_fact_block,
    canonical_ledger_digest,
    canonical_ledger_payload,
)
from capability_exchange.diagnosis.work import AnalysisMode, WorkAudit, queue_digest_for
from capability_exchange.diagnosis.workflows import (
    NodeKind,
    WorkflowGraph,
    WorkflowNode,
)
from capability_exchange.reports import cli
from capability_exchange.reports.ledger import load_and_validate_ledger

#: One evidence identity every run-derived fixture row cites, so each insight
#: stays grounded in a reference the ledger actually holds.
_EVIDENCE = "file-token:invented-strength.md"


def _verified_catalogue_with_keyring():
    signing_key = Ed25519PrivateKey.from_private_bytes(
        b"reports-ledger-test-key".ljust(32, b"!")
    )
    public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    keyring = KeyRing({"reports-ledger-test": base64.b64encode(public_key).decode("ascii")})
    raw = sign_envelope(
        unsigned_envelope(version=5, key_id="reports-ledger-test"), signing_key
    )
    return verify_catalogue_envelope(raw, keyring=keyring, now=NOW), keyring


def _verified_catalogue():
    return _verified_catalogue_with_keyring()[0]


def _insight(prefix: str, kind: InsightKind) -> GroundedInsight:
    return GroundedInsight(
        insight_id=f"{prefix}:invented",
        kind=kind,
        title=f"Invented {prefix}",
        explanation=f"Invented {prefix} explanation bound to fixture evidence.",
        evidence_ids=(_EVIDENCE,),
    )


def _full_ledger(verified) -> ComparisonLedger:
    """A stored ledger carrying every run-derived field the digest binds.

    These are the fields no catalogue can re-derive — the reload has to carry
    them verbatim, so each one gets a value the model defaults cannot produce.
    """
    payload = json.loads(render_catalogue_ledger_template(verified))
    payload["entries"][0].update(
        {
            "disposition": Disposition.STRONG_HERE.value,
            "evidence_references": [_EVIDENCE],
            "reason": "Invented grounded strength for the reload fixture.",
        }
    )
    node = WorkflowNode(
        node_id="node:invented-skill",
        kind=NodeKind.SKILL,
        configuration_state=ConfigurationState.IMPLEMENTED,
        runtime_state=RuntimeState.RECENTLY_RUN,
        health_state=HealthState.HEALTHY,
        evidence_ids=(_EVIDENCE,),
    )
    audit = WorkAudit(
        mode=AnalysisMode.INVENTORY_ONLY,
        packet_count=0,
        packet_ids=(),
        queue_digest=queue_digest_for(AnalysisMode.INVENTORY_ONLY, ()),
        completed_count=0,
        unresolved_count=0,
        manual_submission_count=0,
        receipts=(),
    )
    expectation = SignificantExpectation(
        family_id="capture-and-retrieval",
        state=ExpectationState.PRESENT,
        evidence_ids=(_EVIDENCE,),
        reason="Invented expectation grounded in the fixture evidence.",
    )
    payload.update(
        {
            "workflow_graph": WorkflowGraph(nodes=(node,), edges=()).model_dump(mode="json"),
            "work_audit": audit.model_dump(mode="json"),
            "expectations": [expectation.model_dump(mode="json")],
            "strengths": [_insight("strength", InsightKind.STRENGTH).model_dump(mode="json")],
            "reciprocal_lessons": [
                _insight("lesson", InsightKind.RECIPROCAL_LESSON).model_dump(mode="json")
            ],
            "workflow_insights": [
                _insight("connection", InsightKind.WORKFLOW_CONNECTION).model_dump(mode="json")
            ],
        }
    )
    return ComparisonLedger.model_validate(payload)


#: Every field the reload must account for. A new ledger field fails this on
#: purpose: extend ``_full_ledger`` and the reload in ``reports/ledger.py`` so
#: the new field round-trips, or the saved-report check will vouch for content
#: it never re-reads — the exact hole this file guards against reopening.
_LEDGER_FIELDS = {
    "catalogue_version",
    "catalogue_sha256",
    "capabilities",
    "entries",
    "ranked_recommendations",
    "mcp_tools_by_server",
    "family_entries",
    "version_distance",
    "local_entries",
    "reciprocal_answer",
    "workflow_graph",
    "work_audit",
    "expectations",
    "strengths",
    "reciprocal_lessons",
    "workflow_insights",
}

#: The run-derived fields ``for_catalogue`` used to drop on reload, keyed to a
#: schema-valid tamper of each one — the exact tampers `report check` could
#: not see before the reload carried the full field set.
_RUN_DERIVED_TAMPERS = {
    "workflow_graph": lambda payload: payload["workflow_graph"]["nodes"][0].update(
        {"health_state": "broken"}
    ),
    "work_audit": lambda payload: payload.update({"work_audit": None}),
    "expectations": lambda payload: payload["expectations"][0].update({"state": "absent"}),
    "strengths": lambda payload: payload["strengths"][0].update(
        {"explanation": "Forged strength explanation."}
    ),
    "reciprocal_lessons": lambda payload: payload["reciprocal_lessons"][0].update(
        {"explanation": "Forged lesson explanation."}
    ),
    "workflow_insights": lambda payload: payload["workflow_insights"][0].update(
        {"explanation": "Forged insight explanation."}
    ),
}


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


def test_the_ledger_field_set_is_pinned_to_what_the_reload_carries() -> None:
    """A new ledger field must be wired through the reload before it ships.

    This is the tripwire, not the proof: the round-trip tests below prove the
    named fields survive, and this fails the build the moment a field exists
    that they were never taught about.
    """
    assert set(ComparisonLedger.model_fields) == _LEDGER_FIELDS


def test_reload_carries_every_run_derived_field_the_digest_binds(tmp_path: Path) -> None:
    verified = _verified_catalogue()
    source = _full_ledger(verified)
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(canonical_ledger_payload(source)), encoding="utf-8")

    loaded, problems = load_and_validate_ledger(path, verified)

    assert problems == []
    assert loaded is not None
    assert loaded == source
    assert canonical_ledger_digest(loaded) == canonical_ledger_digest(source)


def test_reload_fails_closed_when_revalidation_loses_a_digest_bound_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reload that projects the ledger must refuse, never narrow it.

    Simulates the next regression of the same shape: a ``for_catalogue`` that
    quietly drops one digest-bound field on revalidation.
    """
    verified = _verified_catalogue()
    source = _full_ledger(verified)
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(canonical_ledger_payload(source)), encoding="utf-8")
    faithful = ComparisonLedger.for_catalogue.__func__

    def dropping(cls, catalogue, **kwargs):
        kwargs.pop("strengths", None)
        return faithful(cls, catalogue, **kwargs)

    monkeypatch.setattr(ComparisonLedger, "for_catalogue", classmethod(dropping))

    loaded, problems = load_and_validate_ledger(path, verified)

    assert loaded is None
    assert problems == [
        "the comparison ledger could not be re-validated faithfully: a field "
        "the ledger digest binds was lost on reload"
    ]


def _grounded_report(ledger: ComparisonLedger) -> str:
    """A report that clears the evidence gate and records its exact ledger.

    The canonical fact block under Coverage and limits is what a real saved
    diagnosis carries; its digest line is the report's own claim about which
    ledger it accounts for.
    """
    return f"""# Invented diagnosis

## What I read
- Invented inventory: `file-token:invented-inventory.md`

## What is working especially well
### Invented review checkpoint — Verified
> Confirm the invented checkpoint before the next step.
> - `file-token:invented-strength.md`

## What Dex should learn from you
### Invented reciprocal method — Verified
> Pair every invented choice with an invented review checkpoint.
> - `file-token:invented-reciprocal.md`

## Worth borrowing from Dex
No Dex addition cleared the evidence bar this time.

## Fragility and contradictions
I checked the rules in `file-token:invented-rules.md` against the
invented skills and found no conflicts.

## Coverage and limits
{canonical_fact_block(ledger)}- Every identity and evidence reference here is invented.

## What happens next
- Strongest grounded capability: the invented review checkpoint.
"""


class TestReportCheckHoldsTheSavedLedgerToItsRecordedDigest:
    """`dex-lens reports check`, run the way a person re-checks a saved pair.

    Before the reload carried the run-derived fields, every tamper in
    ``_RUN_DERIVED_TAMPERS`` passed this exact command: the projection dropped
    the tampered field, so nothing compared it to anything.
    """

    @pytest.fixture
    def saved_pair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path, dict]:
        verified, keyring = _verified_catalogue_with_keyring()
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        from capability_exchange.catalogue.subscription import default_lens_app_storage

        VerifiedCatalogueStore(default_lens_app_storage()).save_verified(verified)
        monkeypatch.setattr(cli, "default_keyring", lambda: keyring)
        ledger = _full_ledger(verified)
        source = tmp_path / "report.md"
        source.write_text(_grounded_report(ledger), encoding="utf-8")
        payload = canonical_ledger_payload(ledger)
        ledger_path = tmp_path / "ledger.json"
        ledger_path.write_text(json.dumps(payload), encoding="utf-8")
        return source, ledger_path, payload

    def test_an_untampered_saved_pair_still_passes(
        self, saved_pair: tuple[Path, Path, dict], capsys: pytest.CaptureFixture[str]
    ) -> None:
        source, ledger_path, _payload = saved_pair

        assert cli.reports_main(["check", str(source), "--ledger", str(ledger_path)]) == 0

        assert "ready to save" in capsys.readouterr().err

    def test_an_untampered_saved_pair_still_saves(
        self, saved_pair: tuple[Path, Path, dict], capsys: pytest.CaptureFixture[str]
    ) -> None:
        source, ledger_path, _payload = saved_pair

        assert (
            cli.reports_main(
                ["save", str(source), "--ledger", str(ledger_path), "--label", "vault"]
            )
            == 0
        )

        assert "report saved" in capsys.readouterr().err

    @pytest.mark.parametrize("field", sorted(_RUN_DERIVED_TAMPERS))
    def test_a_tamper_of_each_run_derived_field_is_refused(
        self,
        field: str,
        saved_pair: tuple[Path, Path, dict],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, _ledger_path, payload = saved_pair
        tampered = copy.deepcopy(payload)
        _RUN_DERIVED_TAMPERS[field](tampered)
        tampered_path = tmp_path / f"tampered-{field}.ledger.json"
        tampered_path.write_text(json.dumps(tampered), encoding="utf-8")

        assert cli.reports_main(["check", str(source), "--ledger", str(tampered_path)]) == 2

        captured = capsys.readouterr()
        assert "does not match the ledger digest this report records" in captured.err
        # The refusal names the mismatch, never the ledger's content.
        assert "Forged" not in captured.err
        assert "broken" not in captured.err

    def test_save_refuses_the_tampered_ledger_too(
        self,
        saved_pair: tuple[Path, Path, dict],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, _ledger_path, payload = saved_pair
        tampered = copy.deepcopy(payload)
        _RUN_DERIVED_TAMPERS["strengths"](tampered)
        tampered_path = tmp_path / "tampered.ledger.json"
        tampered_path.write_text(json.dumps(tampered), encoding="utf-8")

        assert (
            cli.reports_main(
                ["save", str(source), "--ledger", str(tampered_path), "--label", "vault"]
            )
            == 2
        )

        captured = capsys.readouterr()
        assert "nothing was saved" in captured.err.lower()
        assert "does not match the ledger digest this report records" in captured.err

    def test_a_report_recording_a_stale_digest_is_refused(
        self,
        saved_pair: tuple[Path, Path, dict],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A digest written by an older Lens no longer matches recomputation.

        This is the documented refusal for reports saved before the digest
        covered the full ledger: the pair cannot be vouched for, so it is
        named rather than accepted quietly.
        """
        source, ledger_path, _payload = saved_pair
        markdown = source.read_text(encoding="utf-8")
        stale = tmp_path / "stale-report.md"
        digest_line_start = "- Ledger digest: sha256:"
        assert digest_line_start in markdown
        position = markdown.index(digest_line_start) + len(digest_line_start)
        stale.write_text(
            markdown[:position] + "0" * 64 + markdown[position + 64 :],
            encoding="utf-8",
        )

        assert cli.reports_main(["check", str(stale), "--ledger", str(ledger_path)]) == 2

        assert (
            "does not match the ledger digest this report records"
            in capsys.readouterr().err
        )

    def test_a_report_that_records_no_digest_makes_no_binding_claim(
        self,
        saved_pair: tuple[Path, Path, dict],
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The guided template records totals, not a digest; it still checks.

        A hand-written report never claimed one exact ledger, so only the
        catalogue-bound validation applies to the ledger beside it.
        """
        source, ledger_path, _payload = saved_pair
        markdown = source.read_text(encoding="utf-8")
        unbound = tmp_path / "unbound-report.md"
        unbound.write_text(
            "\n".join(
                line
                for line in markdown.splitlines()
                if not line.startswith("- Ledger digest: ")
            )
            + "\n",
            encoding="utf-8",
        )

        assert cli.reports_main(["check", str(unbound), "--ledger", str(ledger_path)]) == 0

        assert "ready to save" in capsys.readouterr().err
