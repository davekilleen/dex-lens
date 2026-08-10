"""M5 stage 9: optional, exact-byte Capability Card contribution."""

from __future__ import annotations

import html
from pathlib import Path

import pytest
from tests.cards.test_model import make_card
from tests.concierge.test_adaptation_journey import _journey, _select

from capability_exchange.cards import build_disclosure_manifest
from capability_exchange.concierge.journey import (
    ConciergeStage,
    ContributionEgressError,
    JourneyStateError,
)
from capability_exchange.concierge.views import render_journey
from capability_exchange.contribution import ContributionState, InMemoryStore, PermissionSet


class RecordingIdentity:
    def __init__(self) -> None:
        self.calls = 0

    def contributor_secret(self) -> bytes:
        self.calls += 1
        return b"synthetic-local-contributor-secret"


class RecordingIntake:
    def __init__(self, *, fail_submit: bool = False) -> None:
        self.submissions: list[tuple[object, ...]] = []
        self.withdrawals: list[str] = []
        self.fail_submit = fail_submit

    def submit(self, payload: bytes, /) -> None:
        self.submissions.append((payload,))
        if self.fail_submit:
            raise RuntimeError("synthetic intake unavailable")

    def withdraw(self, card_version_hash: str, /) -> None:
        self.withdrawals.append(card_version_hash)


def _permissions() -> PermissionSet:
    return PermissionSet(
        review=True,
        storage=True,
        moderation=True,
        attribution=False,
        reuse=False,
        distribution=False,
    )


def _contribution_journey(
    tmp_path: Path,
    *,
    identity: RecordingIdentity,
    intake: RecordingIntake,
    store: InMemoryStore,
):
    journey = _journey(tmp_path)
    journey.configure_contribution(
        identity=identity,
        intake=intake,
        stores=(store,),
    )
    return journey


def _reach_approval(journey):
    card = make_card()
    journey.choose_contribution()
    assert journey.stage is ConciergeStage.CONTRIBUTION_BUILD
    journey.build_contribution(card)
    assert journey.stage is ConciergeStage.CONTRIBUTION_REVIEW
    journey.review_contribution()
    assert journey.stage is ConciergeStage.CONTRIBUTION_DISCLOSE
    manifest = journey.disclose_contribution(("selected_job", "method"))
    assert journey.stage is ConciergeStage.CONTRIBUTION_APPROVE
    return card, manifest


def test_diagnosis_and_adaptation_do_not_require_or_invoke_identity(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake()
    store = InMemoryStore("exchange-cards")
    journey = _contribution_journey(
        tmp_path,
        identity=identity,
        intake=intake,
        store=store,
    )

    assert journey.stage is ConciergeStage.CAPABILITY_MAP
    assert identity.calls == 0
    _select(journey)
    journey.preview_adaptation()
    assert identity.calls == 0
    assert intake.submissions == []


def test_explicit_choice_precedes_identity_and_all_stage_9_transitions(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake()
    store = InMemoryStore("exchange-cards")
    journey = _contribution_journey(
        tmp_path,
        identity=identity,
        intake=intake,
        store=store,
    )

    card, manifest = _reach_approval(journey)
    assert identity.calls == 0
    approval_page = render_journey(journey, csrf_token="csrf")
    normalized_page = " ".join(approval_page.split()).lower()
    assert html.unescape(approval_page).count(manifest.display_text) == 1
    assert str(len(manifest.payload_bytes)) in approval_page
    assert "shipped core releases cannot be recalled" in normalized_page
    assert "separate core-adoption agreement" in normalized_page

    contribution = journey.approve_contribution(_permissions())
    assert journey.stage is ConciergeStage.CONTRIBUTION_SUBMIT
    assert identity.calls == 1
    assert contribution.version_hash == card.version_hash
    assert contribution.manifest == manifest
    assert intake.submissions == []

    submitted = journey.submit_contribution()
    assert journey.stage is ConciergeStage.CONTRIBUTION_WITHDRAW
    assert submitted.state is ContributionState.SUBMITTED
    assert intake.submissions == [(manifest.payload_bytes,)]
    assert store.payloads == {card.version_hash: manifest.payload_bytes}

    withdrawn = journey.withdraw_contribution(reason="person requested withdrawal")
    assert journey.stage is ConciergeStage.CONTRIBUTION_WITHDRAW
    assert withdrawn.state is ContributionState.WITHDRAWN
    assert intake.withdrawals == [card.version_hash]
    assert store.withdrawn_versions == {card.version_hash}
    page = render_journey(journey, csrf_token="csrf")
    assert "Withdrawal is complete" in page
    assert "immediate" in page.lower()


def test_each_transition_fails_closed_without_skipping_a_stage(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake()
    journey = _contribution_journey(
        tmp_path,
        identity=identity,
        intake=intake,
        store=InMemoryStore("exchange-cards"),
    )

    journey.choose_contribution()
    with pytest.raises(JourneyStateError, match="contribution-build"):
        journey.review_contribution()
    assert journey.stage is ConciergeStage.CONTRIBUTION_BUILD
    assert identity.calls == 0
    assert intake.submissions == []


def test_submit_revalidates_exact_card_version_and_manifest_consent(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake()
    journey = _contribution_journey(
        tmp_path,
        identity=identity,
        intake=intake,
        store=InMemoryStore("exchange-cards"),
    )
    _, manifest = _reach_approval(journey)
    journey.approve_contribution(_permissions())

    edited = make_card(method="Use the approved checklist and draft a bounded weekly review.")
    edited_manifest = build_disclosure_manifest(
        edited,
        approved_fields=manifest.approved_fields,
    )
    journey._contribution_manifest = edited_manifest

    with pytest.raises(ContributionEgressError, match="exact approved Card version"):
        journey.submit_contribution()
    assert journey.stage is ConciergeStage.CONTRIBUTION_SUBMIT
    assert intake.submissions == []


def test_intake_failure_quarantines_and_leaves_immediate_withdrawal_available(
    tmp_path: Path,
) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake(fail_submit=True)
    store = InMemoryStore("exchange-cards")
    journey = _contribution_journey(
        tmp_path,
        identity=identity,
        intake=intake,
        store=store,
    )
    card, manifest = _reach_approval(journey)
    journey.approve_contribution(_permissions())

    with pytest.raises(ContributionEgressError, match="intake did not confirm"):
        journey.submit_contribution()
    assert intake.submissions == [(manifest.payload_bytes,)]
    assert journey.stage is ConciergeStage.CONTRIBUTION_WITHDRAW
    assert journey.contribution is not None
    assert journey.contribution.state is ContributionState.QUARANTINED
    assert store.quarantined_versions == {card.version_hash}

    journey.withdraw_contribution(reason="person requested withdrawal")
    assert journey.contribution.state is ContributionState.WITHDRAWN
    assert intake.withdrawals == [card.version_hash]
