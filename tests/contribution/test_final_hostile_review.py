"""Hostile M5 review probes for authority, consent, and withdrawal boundaries."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError
from tests.cards.test_model import make_card

from capability_exchange.cards.disclosure import build_disclosure_manifest
from capability_exchange.cards.model import CardPermissions, CardRights
from capability_exchange.cards.validation import CardValidationError, require_valid_card
from capability_exchange.contribution.consent import (
    ConsentError,
    ConsentLedger,
    ConsentRecord,
    PermissionSet,
)
from capability_exchange.contribution.lifecycle import ContributionLifecycle, InMemoryStore
from capability_exchange.contribution.moderation import ModerationService, ModerationStatus


def _permission_set(**updates: object) -> PermissionSet:
    values: dict[str, object] = {
        "review": True,
        "storage": True,
        "moderation": True,
        "attribution": False,
        "reuse": False,
        "distribution": False,
    }
    values.update(updates)
    return PermissionSet(**values)  # type: ignore[arg-type]


def _ledger_and_contribution(*stores: InMemoryStore):
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    ledger = ConsentLedger()
    ledger.grant(card, manifest, _permission_set())
    lifecycle = ContributionLifecycle(stores=list(stores), consent=ledger)
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"local-secret")
    return card, manifest, ledger, lifecycle, contribution


@pytest.mark.parametrize(
    "nested",
    [
        CardRights.model_construct(license_status="contributor-owned", rights_attested="yes"),
        CardPermissions.model_construct(
            review=1,
            storage=True,
            moderation=True,
            attribution=False,
            reuse=False,
            distribution=False,
        ),
    ],
)
def test_nested_construct_bypasses_are_recursively_revalidated(nested: object) -> None:
    field = "rights" if isinstance(nested, CardRights) else "permissions"
    hostile = make_card().model_copy(update={field: nested})

    with pytest.raises(CardValidationError):
        require_valid_card(hostile)


@pytest.mark.parametrize("value", [1, 0, "true", "false"])
def test_permission_grants_require_exact_booleans(value: object) -> None:
    with pytest.raises(ValidationError):
        _permission_set(review=value)


def test_consent_withdrawn_state_requires_an_exact_boolean() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    record = ConsentRecord.now(card, manifest, _permission_set())

    with pytest.raises(ValidationError):
        ConsentRecord.model_validate({**record.model_dump(), "withdrawn": "false"})


def test_consent_record_revalidates_bypassed_nested_permissions() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    bypassed = PermissionSet.model_construct(
        review="yes",
        storage=True,
        moderation=True,
        attribution=False,
        reuse=False,
        distribution=False,
    )

    with pytest.raises(ValidationError):
        ConsentRecord.now(card, manifest, bypassed)


def test_consent_cannot_be_overwritten_or_escalated_for_the_same_version() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    ledger = ConsentLedger()
    first = ledger.grant(card, manifest, _permission_set(storage=False))

    with pytest.raises(ConsentError, match="immutable"):
        ledger.grant(card, manifest, _permission_set(storage=True))

    assert ledger.require(card, manifest) == first
    assert ledger.require(card, manifest).permissions.storage is False


def test_consent_permissions_cannot_exceed_card_declarations() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))

    with pytest.raises(ConsentError, match="declared"):
        ConsentLedger().grant(card, manifest, _permission_set(reuse=True))


def test_ordinary_submission_never_writes_non_recallable_or_core_stores() -> None:
    controlled = InMemoryStore("exchange-cards")
    non_recallable = InMemoryStore("external-archive", recallable=False)
    core = InMemoryStore("core-release")
    card, manifest, _, lifecycle, contribution = _ledger_and_contribution(
        controlled, non_recallable, core
    )

    lifecycle.submit(contribution)

    assert controlled.payloads == {card.version_hash: manifest.payload_bytes}
    assert non_recallable.payloads == {}
    assert core.payloads == {}


def test_caller_cannot_label_core_as_recallable_to_receive_ordinary_submission() -> None:
    class LyingCoreStore:
        name = "core-release"
        recallable = True

        def __init__(self) -> None:
            self.puts: list[bytes] = []

        def put(self, version_hash: str, payload: bytes) -> None:
            self.puts.append(payload)

        def withdraw(self, version_hash: str) -> None:
            pass

        def quarantine(self, version_hash: str) -> None:
            pass

        def mark_non_recallable(self, version_hash: str) -> None:
            pass

    core = LyingCoreStore()
    _, _, _, lifecycle, contribution = _ledger_and_contribution(core)  # type: ignore[arg-type]

    lifecycle.submit(contribution)

    assert core.puts == []


def test_core_store_policy_cannot_be_mutated_after_construction() -> None:
    core = InMemoryStore("core-release")

    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        core.recallable = True
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        core.name = "cache"


def test_withdraw_and_quarantine_failures_do_not_stop_later_stores() -> None:
    class FullyBrokenStore:
        name = "broken"
        recallable = True

        def put(self, version_hash: str, payload: bytes) -> None:
            pass

        def withdraw(self, version_hash: str) -> None:
            raise RuntimeError("withdraw failed")

        def quarantine(self, version_hash: str) -> None:
            raise RuntimeError("quarantine failed")

        def mark_non_recallable(self, version_hash: str) -> None:
            raise AssertionError("not non-recallable")

    later = InMemoryStore("later")
    _, _, _, lifecycle, contribution = _ledger_and_contribution(  # type: ignore[arg-type]
        FullyBrokenStore(), later
    )
    lifecycle.submit(contribution)

    lifecycle.withdraw(contribution, reason="person requested withdrawal")

    assert later.withdrawn_versions == {contribution.version_hash}


def test_quarantine_failure_does_not_stop_later_stores() -> None:
    class BrokenQuarantineStore:
        name = "broken"
        recallable = True

        def put(self, version_hash: str, payload: bytes) -> None:
            pass

        def withdraw(self, version_hash: str) -> None:
            pass

        def quarantine(self, version_hash: str) -> None:
            raise RuntimeError("quarantine failed")

        def mark_non_recallable(self, version_hash: str) -> None:
            pass

    later = InMemoryStore("later")
    _, _, _, lifecycle, contribution = _ledger_and_contribution(  # type: ignore[arg-type]
        BrokenQuarantineStore(), later
    )
    lifecycle.submit(contribution)

    lifecycle.quarantine(contribution, "intake failed")

    assert later.quarantined_versions == {contribution.version_hash}


def test_default_moderation_can_scan_but_cannot_mint_approval() -> None:
    service = ModerationService()
    card = make_card()

    assert service.scan(card).status is ModerationStatus.SCANNED
    with pytest.raises(ValueError, match="authority"):
        service.approve(
            card,
            rights_attested=True,
            conflict_declared=True,
        )


def test_unallowlisted_scanner_fails_closed() -> None:
    class Scanner:
        scanner_id = "caller-scanner"
        scanner_version = "latest"

        def __call__(self, card: object) -> tuple[()]:
            return ()

    service = ModerationService(scanner=Scanner())

    result = service.scan(make_card())

    assert result.status is ModerationStatus.QUARANTINED
    assert result.reviewable is False


class _PrincipalPort:
    def __init__(self, principal: str) -> None:
        self.principal = principal

    def authenticated_principal(self) -> str:
        return self.principal


class _TestTrust:
    def sign(self, payload: bytes, key_id: str) -> str:
        return f"test:{key_id}:{hashlib.sha256(payload).hexdigest()}"

    def verify(self, payload: bytes, signature: str, key_id: str) -> bool:
        return signature == self.sign(payload, key_id)


def _authorized_moderation(*, reviewer: str = "reviewer", contributor: str = "contributor"):
    trust = _TestTrust()
    return ModerationService(
        eligible_reviewers={"reviewer"},
        reviewer_identity=_PrincipalPort(reviewer),
        contributor_identity=_PrincipalPort(contributor),
        signer=trust,
        verifier=trust,
        attestation_key_id="test-key",
        trusted_key_ids={"test-key"},
    )


def test_approval_identity_is_bound_to_authenticated_ports_not_call_arguments() -> None:
    parameters = inspect.signature(ModerationService.approve).parameters
    assert "reviewer_id" not in parameters
    assert "contributor_ref" not in parameters

    service = _authorized_moderation()
    attestation = service.approve(
        make_card(),
        rights_attested=True,
        conflict_declared=True,
    )

    assert attestation.reviewer_id == "reviewer"
    assert attestation.contributor_id == "contributor"


def test_authenticated_contributor_cannot_self_approve() -> None:
    service = _authorized_moderation(reviewer="reviewer", contributor="reviewer")

    with pytest.raises(ValueError, match="own Card"):
        service.approve(
            make_card(),
            rights_attested=True,
            conflict_declared=True,
        )


def test_unpinned_attestation_key_fails_closed() -> None:
    trust = _TestTrust()
    service = ModerationService(
        eligible_reviewers={"reviewer"},
        reviewer_identity=_PrincipalPort("reviewer"),
        contributor_identity=_PrincipalPort("contributor"),
        signer=trust,
        verifier=trust,
        attestation_key_id="caller-key",
        trusted_key_ids=set(),
    )

    with pytest.raises(ValueError, match="trust root"):
        service.approve(
            make_card(),
            rights_attested=True,
            conflict_declared=True,
        )


def test_moderation_attestation_bypass_is_revalidated_recursively() -> None:
    service = _authorized_moderation()
    card = make_card()
    attestation = service.approve(
        card,
        rights_attested=True,
        conflict_declared=True,
    )

    bypassed = attestation.model_copy(update={"scanner_passed": 1})

    assert service.verify_attestation(card, bypassed) is False


def test_truthy_non_boolean_trust_verdict_cannot_authorize_review() -> None:
    class TruthyTrustPort:
        def attestation_for(self, card: object) -> object:
            return object()

        def verify_attestation(self, card: object, attestation: object) -> int:
            return 1

    card, manifest, ledger, _, _ = _ledger_and_contribution()
    lifecycle = ContributionLifecycle(
        stores=[InMemoryStore("exchange-cards")],
        consent=ledger,
        moderation=TruthyTrustPort(),  # type: ignore[arg-type]
    )
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"local-secret")
    lifecycle.submit(contribution)

    from capability_exchange.contribution.lifecycle import PermissionDenied

    with pytest.raises(PermissionDenied, match="attestation"):
        lifecycle.mark_reviewed(contribution)
