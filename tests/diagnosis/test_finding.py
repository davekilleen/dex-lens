"""Finding schema: three independent axes, structurally honest (#351)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.diagnosis.conftest import item

from capability_exchange.diagnosis import (
    CapabilityState,
    Finding,
    FoundationCapability,
    SafetyBoundary,
)
from capability_exchange.evidence import EvidenceItem, EvidenceLevel, EvidenceState


def finding(
    *,
    capability: FoundationCapability = FoundationCapability.SAFE_CHANGE_RECOVERY,
    job_id: str = "weekly-report",
    capability_state: CapabilityState = CapabilityState.WORKING,
    evidence_level: EvidenceLevel = EvidenceLevel.VERIFIED,
    safety_boundary: SafetyBoundary = SafetyBoundary.UNCLEAR,
    evidence: tuple[EvidenceItem, ...] = (item(EvidenceState.OBSERVED, "receipt:rollback"),),
    uncertainty_notes: tuple[str, ...] = (),
) -> Finding:
    return Finding(
        capability=capability,
        job_id=job_id,
        capability_state=capability_state,
        evidence_level=evidence_level,
        safety_boundary=safety_boundary,
        evidence=evidence,
        uncertainty_notes=uncertainty_notes,
        practical_implication="Proven recovery protects what already works",
        why_it_matters="Recovery you can trust keeps this job's outcome safe to improve",
        recommended_next_move="Rehearse rolling one file back before the next change",
    )


class TestThreeAxes:
    def test_a_valid_three_axis_finding_constructs(self) -> None:
        built = finding()
        assert built.capability_state is CapabilityState.WORKING
        assert built.evidence_level is EvidenceLevel.VERIFIED
        assert built.safety_boundary is SafetyBoundary.UNCLEAR

    @pytest.mark.parametrize(
        "axis", ["capability_state", "evidence_level", "safety_boundary"]
    )
    def test_every_axis_is_required(self, axis: str) -> None:
        payload = finding().model_dump()
        del payload[axis]
        with pytest.raises(ValidationError):
            Finding.model_validate(payload)

    @pytest.mark.parametrize(
        "axis, junk",
        [
            ("capability_state", "healthy"),  # instrument grammar is not an axis
            ("capability_state", "ok"),
            ("evidence_level", "confirmed"),
            ("evidence_level", "observed"),  # R2 state is not a Level
            ("safety_boundary", "certified"),
        ],
    )
    def test_axis_vocabularies_are_closed(self, axis: str, junk: str) -> None:
        payload = finding().model_dump()
        payload[axis] = junk
        with pytest.raises(ValidationError):
            Finding.model_validate(payload)

    def test_working_verified_and_still_overbroad_is_representable(self) -> None:
        """#351 amendment: a capability can be Working and Verified while
        still being Overbroad — the axes are independent."""
        built = finding(safety_boundary=SafetyBoundary.OVERBROAD)
        assert built.capability_state is CapabilityState.WORKING
        assert built.evidence_level is EvidenceLevel.VERIFIED
        assert built.safety_boundary is SafetyBoundary.OVERBROAD


class TestEvidenceLevelIsDerived:
    def test_declared_level_must_match_the_r2_mapping(self) -> None:
        with pytest.raises(ValidationError, match="derived, never asserted"):
            finding(
                evidence=(item(EvidenceState.USER_REPORTED, "note:person-account"),),
                evidence_level=EvidenceLevel.VERIFIED,
            )

    def test_user_reported_evidence_yields_reported(self) -> None:
        built = finding(
            evidence=(item(EvidenceState.USER_REPORTED, "note:person-account"),),
            evidence_level=EvidenceLevel.REPORTED,
        )
        assert built.evidence_level is EvidenceLevel.REPORTED

    def test_no_evidence_must_be_unknown_level(self) -> None:
        with pytest.raises(ValidationError, match="derived, never asserted"):
            finding(
                evidence=(),
                capability_state=CapabilityState.UNKNOWN,
                evidence_level=EvidenceLevel.VERIFIED,
            )

    def test_insufficient_evidence_never_verified(self) -> None:
        with pytest.raises(ValidationError, match="derived, never asserted"):
            finding(
                evidence=(item(EvidenceState.INSUFFICIENT, "path:.claude/skills"),),
                capability_state=CapabilityState.NOT_DEMONSTRATED,
                evidence_level=EvidenceLevel.VERIFIED,
            )


class TestStatesRequireSupport:
    @pytest.mark.parametrize(
        "state", [CapabilityState.WORKING, CapabilityState.PARTIAL]
    )
    def test_working_and_partial_require_claim_supporting_evidence(
        self, state: CapabilityState
    ) -> None:
        with pytest.raises(ValidationError, match="claim-supporting"):
            finding(
                capability_state=state,
                evidence=(item(EvidenceState.INSUFFICIENT, "path:.claude/skills"),),
                evidence_level=EvidenceLevel.UNKNOWN,
            )

    def test_safe_requires_claim_supporting_evidence(self) -> None:
        """Safe is scoped to available evidence: an evidence-free 'safe'
        certification is unrepresentable."""
        with pytest.raises(ValidationError, match="never a blanket"):
            finding(
                capability_state=CapabilityState.UNKNOWN,
                safety_boundary=SafetyBoundary.SAFE,
                evidence=(),
                evidence_level=EvidenceLevel.UNKNOWN,
            )

    def test_safe_is_always_scoped_to_a_job(self) -> None:
        payload = finding(safety_boundary=SafetyBoundary.SAFE).model_dump()
        del payload["job_id"]
        with pytest.raises(ValidationError):
            Finding.model_validate(payload)


class TestClosedSchema:
    def test_extra_fields_are_forbidden(self) -> None:
        payload = finding().model_dump()
        payload["overall"] = 0.9
        with pytest.raises(ValidationError):
            Finding.model_validate(payload)

    def test_findings_are_frozen(self) -> None:
        built = finding()
        with pytest.raises(ValidationError):
            built.capability_state = CapabilityState.UNKNOWN  # type: ignore[misc]

    def test_notes_are_bounded_single_lines(self) -> None:
        with pytest.raises(ValidationError):
            finding(uncertainty_notes=("line one\nline two",))

    def test_next_move_is_singular_by_construction(self) -> None:
        """One recommended next move: the field is a single bounded line,
        not a collection."""
        assert not isinstance(finding().recommended_next_move, (list, tuple))
        with pytest.raises(ValidationError):
            Finding.model_validate(
                {**finding().model_dump(), "recommended_next_move": ["a", "b"]}
            )


# The jobs-first map shapes that nest these findings per confirmed job
# (JobFindings, CapabilityMap) live in capability_exchange.capmap.model and
# are covered by tests/capmap/test_model.py.
