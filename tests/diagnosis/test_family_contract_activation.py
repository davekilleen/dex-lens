"""Release-distance activation through the real signed family-contract path.

Every envelope here is signed with an invented Ed25519 test key that exists
only in this file. The tests drive the real verifier, the real
``VerifiedCatalogueStore`` cache, the real ``CachedCatalogueLoader`` and the
real guided engine — no stand-in catalogue objects — so a signed
``capability_families`` collection is proved to flip
``family_contract_present`` and enable the release-distance specialist end to
end, while unknown keys, tampered bytes and malformed contracts fail closed.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.concierge.test_diagnosis_consent import approved_scope_snapshot as capture_scope
from tests.concierge.test_diagnosis_consent import invented_root
from tests.diagnosis.test_significant_family_assessment import (
    _automation,
    _family,
    _fingerprint,
    _job,
    _mcp,
    _observation,
    _parked_engine,
    _skill,
)

from capability_exchange.catalogue.v2 import (
    CatalogueVerificationError,
    KeyRing,
    VerifiedCatalogueStore,
    canonical_signed_payload,
    verify_catalogue_envelope,
)
from capability_exchange.concierge.consent import LocalScopeConsentAuthority
from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.defaults import (
    CachedCatalogueLoader,
    UnknownUntilProposedComparer,
)
from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.orchestrator import (
    DeterministicDiagnosisEngine,
    PrepareDiagnosisRequest,
)
from capability_exchange.diagnosis.ranking import RecommendationFactors
from capability_exchange.diagnosis.run import (
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    candidate_id_for,
)
from capability_exchange.diagnosis.work import AnalysisMode
from capability_exchange.reports.store import LensReportStore

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)

# Both seeds are invented for these tests only and are obviously not
# production key material; the production key never appears here.
_TEST_SEED = bytes(range(32))
_UNKNOWN_SEED = bytes(255 - value for value in range(32))
_TEST_KEY_ID = "invented-lens-test-key-1"
_UNKNOWN_KEY_ID = "invented-unknown-key-1"

_RELEASE_DISTANCE_REASON = (
    "The signed family contract binds this member, so the release distance for "
    "its outcome family is assessable from signed lineage."
)


def _signing_key(seed: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(seed)


def _keyring_for(key_id: str, seed: bytes) -> KeyRing:
    public = _signing_key(seed).public_key().public_bytes_raw()
    return KeyRing({key_id: base64.b64encode(public).decode("ascii")})


def _test_keyring() -> KeyRing:
    return _keyring_for(_TEST_KEY_ID, _TEST_SEED)


def _family_contract() -> dict[str, object]:
    return _family(
        "durable-task-flow",
        profile="mcp",
        members=["dex-work-mcp"],
        components=[
            {"component_type": "capability", "capability_id": "dex-work-mcp"},
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work-mcp",
                "tool_name": "create_task",
            },
        ],
    )


def _catalogue_payload(*families: dict[str, object]) -> dict[str, object]:
    return {
        "jobs_taxonomy": [_job()],
        "capabilities": [
            _skill("workflow-skill"),
            _skill("dormant-helper", availability="dormant"),
            _mcp(),
            _automation(),
            _parked_engine(),
        ],
        "capability_aliases": [
            {"alias": "work-mcp", "capability_id": "dex-work-mcp"},
        ],
        "capability_families": list(families),
        "portable_brief": {
            "format": "markdown",
            "audience": "the person's own AI system",
            "safety_boundary": "guidance only; it changes nothing",
        },
    }


def _signed_raw(
    catalogue: dict[str, object],
    *,
    seed: bytes = _TEST_SEED,
    key_id: str = _TEST_KEY_ID,
    catalog_version: int = 7,
) -> str:
    envelope = {
        "metadata": {
            "contract_version": "dex-lens-catalogue-v2",
            "catalog_version": catalog_version,
            "produced_at": "2026-01-01T00:00:00Z",
            "expires_at": "2036-01-01T00:00:00Z",
            "producer": "Invented Lens test signer",
            "core_release": "v1.98.0",
            "key_id": key_id,
        },
        "catalogue": catalogue,
    }
    signature = _signing_key(seed).sign(canonical_signed_payload(envelope))
    return json.dumps(
        {**envelope, "signature": base64.b64encode(signature).decode("ascii")},
        sort_keys=True,
    )


def _store_with(raw: str, tmp_path: Path, *, keyring: KeyRing) -> VerifiedCatalogueStore:
    store = VerifiedCatalogueStore(tmp_path)
    store.save_verified(verify_catalogue_envelope(raw, keyring=keyring))
    return store


def test_test_key_signed_family_contract_flips_family_contract_present(
    tmp_path: Path,
) -> None:
    """A signed capability_families collection is the family contract."""

    with_families = _store_with(
        _signed_raw(_catalogue_payload(_family_contract())),
        tmp_path / "with-families",
        keyring=_test_keyring(),
    )
    family_free = _store_with(
        _signed_raw(_catalogue_payload()),
        tmp_path / "family-free",
        keyring=_test_keyring(),
    )

    present = CachedCatalogueLoader(with_families, keyring=_test_keyring()).load(
        run_id="run:" + "1" * 16,
        fingerprint_digest="sha256:" + "2" * 64,
    )
    absent = CachedCatalogueLoader(family_free, keyring=_test_keyring()).load(
        run_id="run:" + "3" * 16,
        fingerprint_digest="sha256:" + "4" * 64,
    )

    assert present.family_contract_present is True
    assert absent.family_contract_present is False


def test_family_contract_signed_by_unknown_key_fails_closed(tmp_path: Path) -> None:
    """A cache written by any other key never becomes a family contract."""

    raw = _signed_raw(
        _catalogue_payload(_family_contract()),
        seed=_UNKNOWN_SEED,
        key_id=_UNKNOWN_KEY_ID,
    )
    with pytest.raises(CatalogueVerificationError, match="unknown catalogue signing key_id"):
        verify_catalogue_envelope(raw, keyring=_test_keyring())

    # The attacker can write their own cache bytes; the pinned keyring still
    # refuses them on every load, so the loader reports no usable catalogue.
    store = _store_with(
        raw, tmp_path, keyring=_keyring_for(_UNKNOWN_KEY_ID, _UNKNOWN_SEED)
    )
    with pytest.raises(DiagnosisStateError, match="verify the Dex catalogue"):
        CachedCatalogueLoader(store, keyring=_test_keyring()).load(
            run_id="run:" + "5" * 16,
            fingerprint_digest="sha256:" + "6" * 64,
        )


def test_tampered_family_contract_bytes_fail_signature_verification() -> None:
    raw = _signed_raw(_catalogue_payload(_family_contract()))
    envelope = json.loads(raw)
    envelope["catalogue"]["capability_families"][0]["outcome"] = (
        "A quietly edited outcome the signer never saw."
    )

    with pytest.raises(CatalogueVerificationError, match="signature verification failed"):
        verify_catalogue_envelope(json.dumps(envelope), keyring=_test_keyring())


def test_malformed_family_contract_fails_closed_even_when_correctly_signed() -> None:
    """A trusted signature does not launder a family that breaks the contract."""

    broken = _family(
        "durable-task-flow",
        profile="mcp",
        members=["capability-that-does-not-exist"],
        components=[
            {
                "component_type": "capability",
                "capability_id": "capability-that-does-not-exist",
            }
        ],
    )
    raw = _signed_raw(_catalogue_payload(broken))

    with pytest.raises(CatalogueVerificationError, match="schema validation failed"):
        verify_catalogue_envelope(raw, keyring=_test_keyring())


class _StaticCollector:
    def __init__(self) -> None:
        self.fingerprint = _fingerprint(
            _observation(ObservationKind.MCP_SERVER, "work-mcp")
        )

    def collect(self, receipt: object) -> object:
        del receipt
        return self.fingerprint


class _GuidedHarness:
    """A real engine over a real test-key-signed catalogue store."""

    def __init__(self, tmp_path: Path, *families: dict[str, object]) -> None:
        raw = _signed_raw(_catalogue_payload(*families))
        self.store = _store_with(raw, tmp_path / "catalogue", keyring=_test_keyring())
        self.root = invented_root(tmp_path)
        self.consent = LocalScopeConsentAuthority(now=lambda: NOW)
        self.run_store = DiagnosisRunStore(tmp_path / "state" / "diagnosis-runs")
        self.engine = DeterministicDiagnosisEngine(
            run_store=self.run_store,
            consent_authority=self.consent,
            collector=_StaticCollector(),
            catalogue_loader=CachedCatalogueLoader(self.store, keyring=_test_keyring()),
            comparer=UnknownUntilProposedComparer(self.store, keyring=_test_keyring()),
            report_store=LensReportStore(tmp_path / "reports"),
            clock=lambda: NOW,
        )

    def start_guided_run(self) -> str:
        view = self.engine.prepare(
            PrepareDiagnosisRequest(roots=(self.root,), analysis_mode=AnalysisMode.GUIDED)
        )
        self.consent.approve_from_local_session(
            run_id=view.run_id,
            scope_snapshot=capture_scope(self.root),
            authenticated_session_id="local-session",
        )
        current = self.engine.status(view.run_id)
        while current.stage is not DiagnosisStage.ANALYSIS_PLANNED:
            current = self.engine.advance(view.run_id)
        return view.run_id

    def release_distance_proposal(self, packet: object) -> SpecialistProposal:
        return SpecialistProposal(
            role=packet.role,
            kind=ProposalKind.RELEASE_DISTANCE,
            run_id=packet.run_id,
            fingerprint_digest=packet.fingerprint_digest,
            catalogue_digest=packet.catalogue_digest,
            packet_id=packet.packet_id,
            packet_digest=packet.packet_digest,
            catalogue_id="dex-work-mcp",
            capability_id="dex-work-mcp",
            candidate_id=candidate_id_for(
                ProposalKind.RELEASE_DISTANCE, "dex-work-mcp", "dex-work-mcp"
            ),
            disposition=Disposition.WORTH_BORROWING,
            recommendation_factors=RecommendationFactors(
                reliability_risk=2,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=2,
            ),
            evidence_ids=(packet.evidence_ids[0],),
            observation_ids=(packet.observation_ids[0],),
            reason=_RELEASE_DISTANCE_REASON,
        )

    def work_to_release_distance_packet(self, run_id: str) -> object:
        while (packet := self.engine.work(run_id)) is not None:
            if packet.role is SpecialistRole.RELEASE_DISTANCE:
                return packet
            self.engine.submit_work(run_id, packet.packet_id, ())
        raise AssertionError("guided queue issued no release-distance packet")


def test_guided_run_accepts_release_distance_proposal_with_signed_contract(
    tmp_path: Path,
) -> None:
    """The real guided run carries a usable release-distance claim to close."""

    harness = _GuidedHarness(tmp_path, _family_contract())
    run_id = harness.start_guided_run()

    packet = harness.work_to_release_distance_packet(run_id)
    harness.engine.submit_work(
        run_id, packet.packet_id, (harness.release_distance_proposal(packet),)
    )
    while (packet := harness.engine.work(run_id)) is not None:
        harness.engine.submit_work(run_id, packet.packet_id, ())
    view = harness.engine.status(run_id)
    while view.stage is not DiagnosisStage.CLOSED:
        view = harness.engine.advance(run_id)

    result = harness.engine.result(run_id)
    entry = next(
        item for item in result.ledger.entries if item.catalogue_id == "dex-work-mcp"
    )
    assert entry.disposition is Disposition.WORTH_BORROWING
    assert entry.reason == _RELEASE_DISTANCE_REASON


def test_guided_run_refuses_release_distance_proposal_without_contract(
    tmp_path: Path,
) -> None:
    """The same run over a family-free signed catalogue fails the same claim."""

    harness = _GuidedHarness(tmp_path)
    run_id = harness.start_guided_run()

    packet = harness.work_to_release_distance_packet(run_id)
    with pytest.raises(SpecialistProposalError, match="rejected") as failure:
        harness.engine.submit_work(
            run_id, packet.packet_id, (harness.release_distance_proposal(packet),)
        )

    assert (
        "release-distance analysis is disabled until a signed capability-family "
        "contract exists"
    ) in str(failure.value.__cause__)
