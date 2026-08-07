"""Deterministic candidate-job proposal tests (M-C propose-confirm flow).

- Proposals are deterministic: same envelope in, identical proposals out.
- Every proposal carries the R2 state ``inferred`` and says so in words —
  never presented as fact.
- Detection proposes; it never enrolls: nothing here can produce a
  Success Contract, only an ``Inspection``-state draft.
- Fail closed: broken / could-not-check instruments and non-observed
  evidence states propose nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from capability_exchange.adapter import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState
from capability_exchange.jobs import (
    CandidateJobProposal,
    InspectionJob,
    SuccessContract,
    propose_candidate_jobs,
    to_inspection_job,
)

COLLECTED_AT = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


def item(state: EvidenceState, reference: str) -> EvidenceItem:
    return EvidenceItem(state=state, captured_at=COLLECTED_AT, reference=reference)


def probe(
    probe_id: str,
    *items: EvidenceItem,
    health: InstrumentHealth = InstrumentHealth.HEALTHY,
    detail: str = "",
) -> ProbeResult:
    return ProbeResult(probe_id=probe_id, health=health, detail=detail, evidence=items)


def envelope(*probes: ProbeResult) -> AdapterResultEnvelope:
    return AdapterResultEnvelope(
        adapter_id="claude-code-macos",
        contract_version="1.0.0",
        collected_at=COLLECTED_AT,
        probes=probes,
    )


def rich_envelope() -> AdapterResultEnvelope:
    return envelope(
        probe("skills-present", item(EvidenceState.OBSERVED, "file:skills-a#snap:k1")),
        probe("instructions-present", item(EvidenceState.OBSERVED, "file:claude-md#snap:k2")),
        probe("settings-present", item(EvidenceState.OBSERVED, "file:settings#snap:k3")),
        probe("installation-shape", item(EvidenceState.OBSERVED, "installation:x#method:y")),
        probe("collection-exclusions", detail=""),
    )


class TestProposalDeterminism:
    def test_same_envelope_produces_identical_proposals(self) -> None:
        first = propose_candidate_jobs(rich_envelope())
        second = propose_candidate_jobs(rich_envelope())
        assert first == second
        assert [p.model_dump(mode="json") for p in first] == [
            p.model_dump(mode="json") for p in second
        ]

    def test_proposals_are_canonically_ordered(self) -> None:
        proposals = propose_candidate_jobs(rich_envelope())
        ids = [p.candidate_id for p in proposals]
        assert ids == sorted(ids)

    def test_probe_order_does_not_change_the_result(self) -> None:
        # The envelope canonicalizes probe order itself; assert end to end.
        forward = rich_envelope()
        reversed_probes = envelope(*reversed(forward.probes))
        assert propose_candidate_jobs(forward) == propose_candidate_jobs(reversed_probes)

    def test_expected_patterns_propose_expected_candidates(self) -> None:
        ids = {p.candidate_id for p in propose_candidate_jobs(rich_envelope())}
        assert ids == {
            "instruction-guided-work",
            "recurring-skill-workflows",
            "tool-configuration-upkeep",
        }


class TestProposalsAreHonestlyInferred:
    def test_every_proposal_evidence_item_is_inferred(self) -> None:
        for proposal in propose_candidate_jobs(rich_envelope()):
            assert proposal.evidence
            for evidence in proposal.evidence:
                assert evidence.state is EvidenceState.INFERRED

    def test_every_rationale_says_inferred_in_words(self) -> None:
        for proposal in propose_candidate_jobs(rich_envelope()):
            assert "inferred" in proposal.rationale.lower()

    def test_observed_state_on_a_proposal_is_unrepresentable(self) -> None:
        with pytest.raises(ValidationError, match="never presented as fact"):
            CandidateJobProposal(
                candidate_id="recurring-skill-workflows",
                title="Possible job: run your recurring skill-based workflows",
                draft_situation="s",
                draft_desired_outcome="o",
                rationale="inferred from observed patterns; a suggestion",
                evidence=(item(EvidenceState.OBSERVED, "file:skills-a#snap:k1"),),
            )

    def test_fact_presented_rationale_is_unrepresentable(self) -> None:
        with pytest.raises(ValidationError, match="inferred"):
            CandidateJobProposal(
                candidate_id="recurring-skill-workflows",
                title="Possible job: run your recurring skill-based workflows",
                draft_situation="s",
                draft_desired_outcome="o",
                rationale="you definitely run recurring workflows",
                evidence=(item(EvidenceState.INFERRED, "file:skills-a#snap:k1"),),
            )

    def test_proposal_requires_evidence(self) -> None:
        with pytest.raises(ValidationError):
            CandidateJobProposal(
                candidate_id="recurring-skill-workflows",
                title="t",
                draft_situation="s",
                draft_desired_outcome="o",
                rationale="inferred; a suggestion",
                evidence=(),
            )


class TestFailClosedProposalGrounds:
    def test_absent_evidence_proposes_nothing(self) -> None:
        result = propose_candidate_jobs(
            envelope(
                probe("skills-present", item(EvidenceState.ABSENT, "skills:none-in-scope"))
            )
        )
        assert result == ()

    @pytest.mark.parametrize(
        "state",
        [
            EvidenceState.STALE,
            EvidenceState.CONFLICTING,
            EvidenceState.USER_REPORTED,
            EvidenceState.INFERRED,
            EvidenceState.NOT_ASSESSED,
        ],
    )
    def test_non_observed_states_propose_nothing(self, state: EvidenceState) -> None:
        result = propose_candidate_jobs(
            envelope(probe("skills-present", item(state, "file:skills-a#snap:k1")))
        )
        assert result == ()

    @pytest.mark.parametrize(
        "health",
        [InstrumentHealth.BROKEN, InstrumentHealth.COULD_NOT_CHECK],
    )
    def test_failed_instruments_propose_nothing(self, health: InstrumentHealth) -> None:
        # A failed instrument cannot carry claim-supporting evidence at all;
        # even its permitted (non-claim) states must ground no proposal.
        result = propose_candidate_jobs(
            envelope(
                probe(
                    "skills-present",
                    item(EvidenceState.BLOCKED, "skills:collection-blocked"),
                    health=health,
                    detail="instrument failed and says so",
                )
            )
        )
        assert result == ()

    def test_intentionally_off_with_no_observation_proposes_nothing(self) -> None:
        result = propose_candidate_jobs(
            envelope(
                probe(
                    "skills-present",
                    health=InstrumentHealth.INTENTIONALLY_OFF,
                    detail="the person turned this area off deliberately",
                )
            )
        )
        assert result == ()

    def test_unmapped_probes_propose_nothing(self) -> None:
        result = propose_candidate_jobs(
            envelope(
                probe(
                    "installation-shape",
                    item(EvidenceState.OBSERVED, "installation:x#method:y"),
                )
            )
        )
        assert result == ()


class TestDetectionNeverEnrolls:
    def test_kept_proposal_becomes_an_inspection_draft(self) -> None:
        proposal = propose_candidate_jobs(rich_envelope())[0]
        job = to_inspection_job(proposal, created_at=COLLECTED_AT)
        assert isinstance(job, InspectionJob)
        assert job.lifecycle == "inspection"
        assert job.job_id == proposal.candidate_id
        assert job.evidence_references  # references only, never evidence items

    def test_nothing_in_the_module_returns_a_success_contract(self) -> None:
        proposals = propose_candidate_jobs(rich_envelope())
        for proposal in proposals:
            drafted = to_inspection_job(proposal, created_at=COLLECTED_AT)
            assert not isinstance(drafted, SuccessContract)
            assert not isinstance(proposal, SuccessContract)

    def test_draft_carries_deduplicated_references(self) -> None:
        proposal = CandidateJobProposal(
            candidate_id="recurring-skill-workflows",
            title="Possible job: run your recurring skill-based workflows",
            draft_situation="s",
            draft_desired_outcome="o",
            rationale="inferred from repeated patterns; a suggestion",
            evidence=(
                item(EvidenceState.INFERRED, "file:skills-a#snap:k1"),
                item(EvidenceState.INFERRED, "file:skills-a#snap:k1"),
                item(EvidenceState.INFERRED, "file:skills-b#snap:k2"),
            ),
        )
        job = to_inspection_job(proposal, created_at=COLLECTED_AT)
        assert job.evidence_references == (
            "file:skills-a#snap:k1",
            "file:skills-b#snap:k2",
        )


class TestProposalDeterminismProperty:
    @given(
        states=st.lists(
            st.sampled_from(list(EvidenceState)), min_size=1, max_size=4
        )
    )
    def test_proposals_are_a_pure_function_of_the_envelope(
        self, states: list[EvidenceState]
    ) -> None:
        items = tuple(
            item(state, f"file:sample-{index}#snap:k{index}")
            for index, state in enumerate(states)
        )
        built = envelope(probe("skills-present", *items))
        again = envelope(probe("skills-present", *items))
        assert propose_candidate_jobs(built) == propose_candidate_jobs(again)
        # And proposals exist exactly when a directly observed item does.
        expects = any(state is EvidenceState.OBSERVED for state in states)
        assert bool(propose_candidate_jobs(built)) is expects
