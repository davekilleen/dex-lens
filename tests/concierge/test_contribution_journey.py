"""M5 stage 9: optional, exact-byte Capability Card contribution."""

from __future__ import annotations

import html
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.cards.test_model import make_card
from tests.concierge.test_adaptation_journey import _journey, _select

from capability_exchange.cards import CapabilityCard, build_disclosure_manifest
from capability_exchange.concierge.journey import (
    ConciergeStage,
    ContributionEgressError,
    ContributionIntakePort,
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
        self.withdrawals: list[object] = []
        self.fail_submit = fail_submit

    def submit(self, payload: bytes, /, *, handle: object) -> object:
        self.submissions.append((payload,))
        if self.fail_submit:
            raise RuntimeError("synthetic intake unavailable")
        return SimpleNamespace(
            manifest_byte_hash=handle.manifest_byte_hash,
            handle_binding=handle.receipt_binding,
            accepted=True,
        )

    def withdraw(self, handle: object, /) -> object:
        self.withdrawals.append(handle)
        return SimpleNamespace(
            manifest_byte_hash=handle.manifest_byte_hash,
            handle_binding=handle.receipt_binding,
            withdrawn=True,
        )


class StructuredIntake:
    def __init__(
        self,
        *,
        accept_submission: bool = True,
        confirm_withdrawal: bool = True,
        fail_withdrawal: bool = False,
    ) -> None:
        self.submissions: list[tuple[bytes, object]] = []
        self.withdrawals: list[object] = []
        self.accept_submission = accept_submission
        self.confirm_withdrawal = confirm_withdrawal
        self.fail_withdrawal = fail_withdrawal

    def submit(self, payload: bytes, /, *, handle: object) -> object:
        self.submissions.append((payload, handle))
        return SimpleNamespace(
            manifest_byte_hash=handle.manifest_byte_hash,
            handle_binding=handle.receipt_binding,
            accepted=self.accept_submission,
        )

    def withdraw(self, handle: object, /) -> object:
        self.withdrawals.append(handle)
        if self.fail_withdrawal:
            raise RuntimeError("synthetic withdrawal unavailable")
        return SimpleNamespace(
            manifest_byte_hash=handle.manifest_byte_hash,
            handle_binding=handle.receipt_binding,
            withdrawn=self.confirm_withdrawal,
        )


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
    from capability_exchange.concierge.journey import AdaptationRefusedError

    with pytest.raises(AdaptationRefusedError, match="outcome procedure"):
        _select(journey)
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
    assert len(intake.withdrawals) == 1
    assert intake.withdrawals[0].manifest_byte_hash == manifest.byte_hash
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


def test_edit_redacts_into_new_version_and_clears_disclosure(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake()
    journey = _contribution_journey(
        tmp_path,
        identity=identity,
        intake=intake,
        store=InMemoryStore("exchange-cards"),
    )
    original, old_manifest = _reach_approval(journey)
    revised = make_card(
        version=original.version + 1,
        method="Use a redacted, bounded weekly review.",
    )

    comparison = journey.edit_contribution(revised)

    assert journey.stage is ConciergeStage.CONTRIBUTION_REVIEW
    assert journey.contribution_card == revised
    assert journey.contribution_manifest is None
    assert comparison.previous_version_hash == original.version_hash
    assert comparison.revised_version_hash == revised.version_hash
    assert comparison.changed_fields == ("version", "method")
    assert old_manifest.byte_hash not in comparison.revised_exact_json
    assert identity.calls == 0
    assert intake.submissions == []
    page = render_journey(journey, csrf_token="csrf")
    assert 'action="/contribution/edit"' in page
    assert "Previous exact JSON" in page
    assert "Revised exact JSON" in page
    assert 'name="approved_field"' not in page


@pytest.mark.parametrize(
    "updates, message",
    (
        ({"version": 2}, "content field"),
        ({"card_id": "different-card", "version": 2}, "same card_id"),
        ({"version": 3, "method": "A changed method."}, "exactly one"),
    ),
)
def test_edit_refuses_noop_identity_change_and_version_jump(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    journey = _contribution_journey(
        tmp_path,
        identity=RecordingIdentity(),
        intake=RecordingIntake(),
        store=InMemoryStore("exchange-cards"),
    )
    original, _ = _reach_approval(journey)
    payload = original.model_dump(mode="json")
    payload.update(updates)
    edited = CapabilityCard.model_validate(payload)

    with pytest.raises(JourneyStateError, match=message):
        journey.edit_contribution(edited)

    assert journey.contribution_card == original
    assert journey.stage is ConciergeStage.CONTRIBUTION_APPROVE


def test_edited_version_requires_fresh_disclosure_and_approval(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    journey = _contribution_journey(
        tmp_path,
        identity=identity,
        intake=RecordingIntake(),
        store=InMemoryStore("exchange-cards"),
    )
    original, _ = _reach_approval(journey)
    first = journey.approve_contribution(_permissions())
    old_ledger = journey._contribution_consent
    assert old_ledger is not None
    assert old_ledger.is_current(first.card, first.manifest)
    assert journey.stage is ConciergeStage.CONTRIBUTION_SUBMIT
    revised = make_card(
        version=original.version + 1,
        method="Use only the explicitly redacted checklist.",
    )
    journey.edit_contribution(revised)
    assert not old_ledger.is_current(first.card, first.manifest)

    with pytest.raises(JourneyStateError, match="contribution-review"):
        journey.approve_contribution(_permissions())
    assert identity.calls == 1

    journey.review_contribution()
    manifest = journey.disclose_contribution(("selected_job", "method"))
    contribution = journey.approve_contribution(_permissions())
    assert contribution.version_hash == revised.version_hash
    assert contribution.manifest == manifest
    assert identity.calls == 2


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


def test_identity_transport_failure_is_reported_as_a_fail_closed_journey_error(
    tmp_path: Path,
) -> None:
    class UnavailableIdentity:
        def contributor_secret(self) -> bytes:
            raise RuntimeError("linked session unavailable")

    journey = _contribution_journey(  # type: ignore[arg-type]
        tmp_path,
        identity=UnavailableIdentity(),
        intake=StructuredIntake(),
        store=InMemoryStore("exchange-cards"),
    )
    _reach_approval(journey)

    with pytest.raises(ContributionEgressError, match="contributor authority unavailable"):
        journey.approve_contribution(_permissions())
    assert journey.stage is ConciergeStage.CONTRIBUTION_APPROVE


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
    assert len(intake.withdrawals) == 1
    assert intake.withdrawals[0].manifest_byte_hash == manifest.byte_hash


def test_intake_submit_keeps_exact_payload_as_only_body_and_requires_bound_receipt(
    tmp_path: Path,
) -> None:
    identity = RecordingIdentity()
    intake = StructuredIntake()
    store = InMemoryStore("exchange-cards")
    journey = _contribution_journey(  # type: ignore[arg-type]
        tmp_path,
        identity=identity,
        intake=intake,
        store=store,
    )
    card, manifest = _reach_approval(journey)
    journey.approve_contribution(_permissions())

    journey.submit_contribution()

    assert len(intake.submissions) == 1
    payload, handle = intake.submissions[0]
    assert payload == manifest.payload_bytes
    assert type(payload) is bytes
    assert handle.manifest_byte_hash == manifest.byte_hash
    assert handle.revocation_token
    assert card.version_hash not in repr(handle)


def test_intake_protocol_has_one_positional_body_plus_keyword_only_handle() -> None:
    parameters = tuple(inspect.signature(ContributionIntakePort.submit).parameters.values())
    assert tuple(parameter.name for parameter in parameters) == ("self", "payload", "handle")
    assert parameters[1].kind is inspect.Parameter.POSITIONAL_ONLY
    assert parameters[1].annotation in {bytes, "bytes"}
    assert parameters[2].kind is inspect.Parameter.KEYWORD_ONLY


def test_mismatched_or_negative_submission_receipt_quarantines(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = StructuredIntake(accept_submission=False)
    store = InMemoryStore("exchange-cards")
    journey = _contribution_journey(  # type: ignore[arg-type]
        tmp_path,
        identity=identity,
        intake=intake,
        store=store,
    )
    card, _ = _reach_approval(journey)
    journey.approve_contribution(_permissions())

    with pytest.raises(ContributionEgressError, match="receipt"):
        journey.submit_contribution()

    assert journey.contribution is not None
    assert journey.contribution.state is ContributionState.QUARANTINED
    assert store.quarantined_versions == {card.version_hash}


def test_noop_withdrawal_receipt_never_counts_as_confirmation(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = StructuredIntake(confirm_withdrawal=False)
    journey = _contribution_journey(  # type: ignore[arg-type]
        tmp_path,
        identity=identity,
        intake=intake,
        store=InMemoryStore("exchange-cards"),
    )
    _reach_approval(journey)
    journey.approve_contribution(_permissions())
    journey.submit_contribution()

    with pytest.raises(ContributionEgressError, match="not confirmed"):
        journey.withdraw_contribution(reason="person requested withdrawal")

    assert journey.has_pending_withdrawal
    page = render_journey(journey, csrf_token="csrf")
    assert "Withdrawal is complete" not in page
    assert "still pending" in page


def test_close_revokes_accepted_submission_and_expired_close_can_be_retried(
    tmp_path: Path,
) -> None:
    identity = RecordingIdentity()
    intake = StructuredIntake(fail_withdrawal=True)
    journey = _contribution_journey(  # type: ignore[arg-type]
        tmp_path,
        identity=identity,
        intake=intake,
        store=InMemoryStore("exchange-cards"),
    )
    _reach_approval(journey)
    journey.approve_contribution(_permissions())
    journey.submit_contribution()

    journey.close()

    assert journey.stage is ConciergeStage.CLOSED
    assert journey.has_pending_withdrawal
    intake.fail_withdrawal = False
    receipt = journey.retry_pending_withdrawal()
    assert receipt.withdrawn is True
    assert not journey.has_pending_withdrawal


def test_close_preserves_an_accepted_durable_review_submission(tmp_path: Path) -> None:
    class DurableIntake(StructuredIntake):
        def has_durable_withdrawal_authority(self, _handle: object, /) -> bool:
            return True

    identity = RecordingIdentity()
    intake = DurableIntake()
    journey = _contribution_journey(  # type: ignore[arg-type]
        tmp_path,
        identity=identity,
        intake=intake,
        store=InMemoryStore("exchange-cards"),
    )
    _reach_approval(journey)
    journey.approve_contribution(_permissions())
    journey.submit_contribution()

    journey.close()

    assert journey.stage is ConciergeStage.CLOSED
    assert intake.withdrawals == []
    assert not journey.has_pending_withdrawal


def test_close_does_not_trust_a_boolean_durable_receipt_claim(tmp_path: Path) -> None:
    class FlagOnlyIntake(StructuredIntake):
        retain_accepted_submission_after_session = True

    intake = FlagOnlyIntake()
    journey = _contribution_journey(  # type: ignore[arg-type]
        tmp_path,
        identity=RecordingIdentity(),
        intake=intake,
        store=InMemoryStore("exchange-cards"),
    )
    _reach_approval(journey)
    journey.approve_contribution(_permissions())
    journey.submit_contribution()

    journey.close()

    assert len(intake.withdrawals) == 1
    assert not journey.has_pending_withdrawal


def test_broken_local_store_does_not_prevent_intake_withdrawal(tmp_path: Path) -> None:
    class BrokenStore:
        name = "broken"
        recallable = True

        def put(self, version_hash: str, payload: bytes) -> None:
            pass

        def withdraw(self, version_hash: str) -> None:
            raise RuntimeError("withdraw failed")

        def quarantine(self, version_hash: str) -> None:
            raise RuntimeError("quarantine failed")

        def mark_non_recallable(self, version_hash: str) -> None:
            pass

    identity = RecordingIdentity()
    intake = StructuredIntake()
    journey = _journey(tmp_path)
    journey.configure_contribution(identity=identity, intake=intake, stores=(BrokenStore(),))
    _reach_approval(journey)
    journey.approve_contribution(_permissions())
    journey.submit_contribution()

    with pytest.raises(ContributionEgressError, match="controlled-store"):
        journey.withdraw_contribution(reason="person requested withdrawal")

    assert len(intake.withdrawals) == 1


def test_close_preserves_failed_local_store_withdrawal_for_retry(tmp_path: Path) -> None:
    class RecoverableStore:
        name = "recoverable"
        recallable = True

        def __init__(self) -> None:
            self.fail = True
            self.withdrawn: set[str] = set()

        def put(self, version_hash: str, payload: bytes) -> None:
            pass

        def withdraw(self, version_hash: str) -> None:
            if self.fail:
                raise RuntimeError("withdraw failed")
            self.withdrawn.add(version_hash)

        def quarantine(self, version_hash: str) -> None:
            if self.fail:
                raise RuntimeError("quarantine failed")

        def mark_non_recallable(self, version_hash: str) -> None:
            pass

    identity = RecordingIdentity()
    intake = StructuredIntake()
    store = RecoverableStore()
    journey = _journey(tmp_path)
    journey.configure_contribution(identity=identity, intake=intake, stores=(store,))
    card, _ = _reach_approval(journey)
    journey.approve_contribution(_permissions())
    journey.submit_contribution()

    journey.close()

    assert journey.has_pending_withdrawal
    assert len(intake.withdrawals) == 1
    store.fail = False
    receipt = journey.retry_pending_withdrawal()
    assert receipt.withdrawn is True
    assert store.withdrawn == {card.version_hash}
    assert not journey.has_pending_withdrawal
