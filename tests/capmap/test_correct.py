"""Correction flow caps (M-D; #352, R1, R2).

The person can correct both the supporting evidence and the job definition:

- an evidence correction routes back as a NEW user-reported R2 evidence
  item whose own contribution caps at Reported;
- a correction NEVER silently upgrades an Evidence Level;
- a job-definition correction re-enters the R1 ``Inspection`` confirmation
  flow — nothing on the correction path can mint a Success Contract.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.capmap.conftest import COLLECTED_AT, contract, one_job_map, two_job_map

from capability_exchange.capmap import (
    CapabilityMap,
    CorrectionError,
    correct_supporting_evidence,
    reopen_job_definition,
)
from capability_exchange.capmap.model import JobFindings
from capability_exchange.diagnosis import (
    CapabilityState,
    Finding,
    FoundationCapability,
    SafetyBoundary,
    assess,
)
from capability_exchange.evidence import (
    EvidenceItem,
    EvidenceLevel,
    EvidenceState,
    evidence_level,
)
from capability_exchange.jobs import (
    InspectionJob,
    InspectionJobStore,
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)

CORRECTED_AT = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
CAPABILITY = FoundationCapability.SAFE_CHANGE_RECOVERY


def _correct(map_: CapabilityMap, **overrides: object) -> CapabilityMap:
    arguments: dict[str, object] = {
        "job_id": "weekly-report",
        "capability": CAPABILITY,
        "account": "The rollback path exists; I used it last month",
        "corrected_at": CORRECTED_AT,
    }
    arguments.update(overrides)
    return correct_supporting_evidence(map_, **arguments)  # type: ignore[arg-type]


def _finding(map_: CapabilityMap, capability: FoundationCapability = CAPABILITY) -> Finding:
    (job,) = [job for job in map_.jobs if job.job_id == "weekly-report"]
    (finding,) = [f for f in job.findings if f.capability is capability]
    return finding


def _map_with_states(states: tuple[EvidenceState, ...]) -> CapabilityMap:
    """A one-job map whose SAFE_CHANGE_RECOVERY finding rests on exactly
    the given prior evidence states (empty tuple → no evidence at all)."""
    base = one_job_map()
    (job,) = base.jobs
    evidence = tuple(
        EvidenceItem(
            state=state,
            captured_at=COLLECTED_AT,
            reference=f"probe:prior-{index}",
        )
        for index, state in enumerate(states)
    )
    has_support = any(
        item.state
        in (EvidenceState.OBSERVED, EvidenceState.USER_REPORTED, EvidenceState.INFERRED)
        for item in evidence
    )
    original = _finding(base)
    replaced = Finding(
        capability=original.capability,
        job_id=original.job_id,
        capability_state=(
            CapabilityState.NOT_DEMONSTRATED if has_support else CapabilityState.UNKNOWN
        ),
        evidence_level=evidence_level(item.state for item in evidence),
        safety_boundary=SafetyBoundary.UNCLEAR,
        evidence=evidence,
        uncertainty_notes=original.uncertainty_notes,
        practical_implication=original.practical_implication,
        why_it_matters=original.why_it_matters,
        recommended_next_move=original.recommended_next_move,
    )
    new_job = JobFindings(
        contract=job.contract,
        findings=tuple(
            replaced if f.capability is CAPABILITY else f for f in job.findings
        ),
    )
    return CapabilityMap(assessed_at=base.assessed_at, jobs=(new_job,))


class TestEvidenceCorrectionsAreUserReported:
    def test_a_correction_becomes_a_new_user_reported_item(self) -> None:
        before = _finding(one_job_map())
        after = _finding(_correct(one_job_map()))
        added = set(after.evidence) - set(before.evidence)
        assert len(added) == 1
        (item,) = added
        assert item.state is EvidenceState.USER_REPORTED
        assert item.captured_at == CORRECTED_AT
        assert item.reference.startswith("user-correction:")

    def test_the_correction_route_cannot_claim_any_other_state(self) -> None:
        """The API accepts no evidence state at all: user-reported is the
        only state a correction can produce, by construction."""
        parameters = inspect.signature(correct_supporting_evidence).parameters
        assert "state" not in parameters
        annotations = " ".join(str(p.annotation) for p in parameters.values())
        assert "EvidenceState" not in annotations

    def test_a_lone_correction_caps_at_reported(self) -> None:
        corrected = _finding(_correct(_map_with_states(())))
        assert corrected.evidence_level is EvidenceLevel.REPORTED

    def test_the_persons_account_stays_visible_and_honest(self) -> None:
        corrected = _finding(_correct(one_job_map()))
        joined = " ".join(corrected.uncertainty_notes)
        assert "The rollback path exists; I used it last month" in joined
        assert "recorded as reported evidence, never as direct inspection" in joined

    def test_axes_other_than_the_level_are_untouched(self) -> None:
        before = _finding(one_job_map())
        after = _finding(_correct(one_job_map()))
        assert after.capability_state is before.capability_state
        assert after.safety_boundary is before.safety_boundary

    def test_a_multi_line_account_is_refused(self) -> None:
        with pytest.raises(Exception, match="line breaks|control"):
            _correct(one_job_map(), account="line one\nline two")

    def test_an_unbounded_account_is_refused(self) -> None:
        with pytest.raises(CorrectionError, match="too long"):
            _correct(one_job_map(), account="x" * 500)

    def test_an_unknown_job_is_refused(self) -> None:
        with pytest.raises(CorrectionError, match="no confirmed job"):
            _correct(one_job_map(), job_id="never-confirmed")

    def test_a_non_capability_target_is_refused(self) -> None:
        with pytest.raises(CorrectionError, match="Foundation Capabilities"):
            _correct(one_job_map(), capability="ownership-portability")


class TestACorrectionNeverSilentlyUpgrades:
    @given(
        states=st.tuples()
        | st.tuples(st.sampled_from(EvidenceState))
        | st.tuples(st.sampled_from(EvidenceState), st.sampled_from(EvidenceState))
        | st.tuples(
            st.sampled_from(EvidenceState),
            st.sampled_from(EvidenceState),
            st.sampled_from(EvidenceState),
        )
    )
    def test_over_every_prior_state_combination(
        self, states: tuple[EvidenceState, ...]
    ) -> None:
        before = _finding(_map_with_states(states))
        after = _finding(_correct(_map_with_states(states)))
        # The correction's own contribution caps at Reported: the level
        # never exceeds what the prior evidence supported, except for the
        # honest Unknown → Reported movement recording that the person's
        # account now exists.
        assert after.evidence_level.rank() <= max(
            before.evidence_level.rank(), EvidenceLevel.REPORTED.rank()
        )
        if after.evidence_level is not before.evidence_level:
            # any movement is announced, never silent
            assert before.evidence_level is EvidenceLevel.UNKNOWN
            assert after.evidence_level is EvidenceLevel.REPORTED
            assert any(
                "moved the Evidence Level" in note for note in after.uncertainty_notes
            )

    def test_a_correction_never_reaches_verified_or_supported_alone(self) -> None:
        for states in ((), (EvidenceState.BLOCKED,), (EvidenceState.ABSENT,)):
            after = _finding(_correct(_map_with_states(states)))
            assert after.evidence_level in (
                EvidenceLevel.REPORTED,
                EvidenceLevel.UNKNOWN,
            )

    def test_a_verified_finding_stays_verified_not_more(self) -> None:
        before = _finding(_map_with_states((EvidenceState.OBSERVED,)))
        assert before.evidence_level is EvidenceLevel.VERIFIED
        after = _finding(_correct(_map_with_states((EvidenceState.OBSERVED,))))
        assert after.evidence_level is EvidenceLevel.VERIFIED


class TestJobEditsReenterInspection:
    def test_a_job_edit_returns_an_inspection_draft(self) -> None:
        reopened = reopen_job_definition(
            one_job_map(),
            job_id="weekly-report",
            reopened_at=CORRECTED_AT,
            desired_outcome="A finished report my team can read unedited",
        )
        assert isinstance(reopened.draft, InspectionJob)
        assert reopened.draft.lifecycle == "inspection"
        assert reopened.draft.desired_outcome == (
            "A finished report my team can read unedited"
        )
        # unedited text carries over for review
        assert reopened.draft.situation == contract().situation

    def test_nothing_on_the_correction_path_mints_a_contract(self) -> None:
        reopened = reopen_job_definition(
            one_job_map(), job_id="weekly-report", reopened_at=CORRECTED_AT
        )
        assert not isinstance(reopened.draft, SuccessContract)
        return_annotations = str(
            inspect.signature(reopen_job_definition).return_annotation
        )
        assert "SuccessContract" not in return_annotations

    def test_the_reopened_job_leaves_the_map(self) -> None:
        reopened = reopen_job_definition(
            two_job_map(), job_id="alpha-job", reopened_at=CORRECTED_AT
        )
        assert reopened.remaining_map is not None
        assert [job.job_id for job in reopened.remaining_map.jobs] == ["beta-job"]

    def test_reopening_the_only_job_leaves_no_map(self) -> None:
        reopened = reopen_job_definition(
            one_job_map(), job_id="weekly-report", reopened_at=CORRECTED_AT
        )
        assert reopened.remaining_map is None

    def test_the_draft_keeps_only_non_raw_evidence_references(self) -> None:
        reopened = reopen_job_definition(
            one_job_map(), job_id="weekly-report", reopened_at=CORRECTED_AT
        )
        map_references = {
            item.reference
            for job in one_job_map().jobs
            for finding in job.findings
            for item in finding.evidence
        }
        assert set(reopened.draft.evidence_references) == map_references

    def test_an_unknown_job_is_refused(self) -> None:
        with pytest.raises(CorrectionError, match="no confirmed job"):
            reopen_job_definition(
                one_job_map(), job_id="never-confirmed", reopened_at=CORRECTED_AT
            )

    def test_full_r1_round_trip_confirmation_is_the_only_exit(
        self, tmp_path
    ) -> None:
        """The reopened draft goes through the real store: save, then only
        an explicit confirm() call yields a contract that can drive
        diagnosis again."""
        from tests.diagnosis.conftest import presence_only_envelope

        reopened = reopen_job_definition(
            one_job_map(),
            job_id="weekly-report",
            reopened_at=CORRECTED_AT,
            desired_outcome="A finished report my team can read unedited",
        )
        store = InspectionJobStore(tmp_path)
        store.save(reopened.draft)
        loaded = store.load("weekly-report")
        assert loaded.lifecycle == "inspection"
        confirmed = store.confirm(
            "weekly-report",
            success_evidence=("the report goes out unedited",),
            boundaries=JobBoundaries(
                privacy_limits=("never read personal mail",),
                approval_limits=("sending anything requires approval",),
                autonomy_limits=("no changes without a person present",),
            ),
            importance=JobImportance.HIGH,
            cadence=JobCadence.WEEKLY,
            confirmed_at=CORRECTED_AT,
        )
        assert isinstance(confirmed, SuccessContract)
        remapped = assess([confirmed], presence_only_envelope())
        assert remapped.jobs[0].contract.desired_outcome == (
            "A finished report my team can read unedited"
        )
