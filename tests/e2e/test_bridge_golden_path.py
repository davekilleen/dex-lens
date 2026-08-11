from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import sign_envelope, unsigned_envelope
from tests.concierge.test_fallback_e2e import _fallback, _permission
from tests.concierge.test_local_server import envelope

from capability_exchange.catalogue.fetch import (
    CONSENT_STATEMENT,
    CatalogueFetchConsent,
    CatalogueFetchStatus,
    ConsentedCatalogueFetcher,
)
from capability_exchange.catalogue.v2 import KeyRing, VerifiedCatalogueStore
from capability_exchange.concierge.journey import ConciergeJourney, FallbackEvidence
from capability_exchange.concierge.server import new_session
from capability_exchange.evidence import EvidenceLevel
from capability_exchange.jobs import InspectionJobStore

NOW = datetime(2026, 8, 11, 19, 30, tzinfo=UTC)
HOST_FIXTURE_ROOT = Path("tests/e2e/hosts").resolve()
EVIDENCE_PACK = Path("docs/pilot/bridge-evidence.md")


class StaticCatalogueHTTP:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.requests: list[object] = []

    def __call__(self, request: object, *, timeout: float) -> object:
        self.requests.append(request)
        return _Response(self.payload)


class _Response:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _signed_catalogue() -> tuple[str, KeyRing]:
    signing_key = Ed25519PrivateKey.from_private_bytes(
        b"dex-lens-catalogue-v2-test-key!!"
    )
    public_key = signing_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    return sign_envelope(unsigned_envelope(), signing_key), KeyRing(
        {"dex-core-2026-08-test": base64.b64encode(public_key).decode("ascii")}
    )


def _confirm_session_jobs(session) -> None:
    session.approve_scope_and_collect()
    for job_id in session.journey.job_ids:
        session.confirm_job(
            {
                "job_id": [job_id],
                "success_evidence": ["the confirmed outcome is visible"],
                "privacy_limits": ["stay local"],
                "approval_limits": ["ask first"],
                "autonomy_limits": ["do not change files"],
                "importance": ["high"],
                "cadence": ["weekly"],
            }
        )
    session.diagnose()


def _brief_from_deep_host(host_root: Path, tmp_path: Path) -> str:
    raw_catalogue, keyring = _signed_catalogue()
    http = StaticCatalogueHTTP(raw_catalogue)
    store = VerifiedCatalogueStore(tmp_path / f"{host_root.name}-state")
    fetcher = ConsentedCatalogueFetcher(
        store=store,
        keyring=keyring,
        urlopen=http,
        now=lambda: NOW,
    )
    session = new_session(
        approved_roots=(host_root,),
        collector=envelope,
        now=lambda: NOW,
        catalogue_fetcher=fetcher,
        app_storage=tmp_path / f"{host_root.name}-app",
    )
    _confirm_session_jobs(session)
    result = session.fetch_catalogue(
        {
            "catalogue_consent": [CONSENT_STATEMENT],
            "catalogue_url": ["https://heydex.ai/catalogue/dex-lens/v2.json"],
        }
    )
    assert result.status is CatalogueFetchStatus.VERIFIED
    assert len(http.requests) == 1
    session.open_catalogue_shelf()
    first = session.journey.catalogue_shelf[0]
    session.select_catalogue_brief(
        {
            "capability_id": [first.capability_id],
            "job_id": [first.matched_job_ids[0]],
        }
    )
    return session.journey.catalogue_brief_markdown


def _brief_from_guided_host(host_root: Path, tmp_path: Path) -> str:
    raw_catalogue, keyring = _signed_catalogue()
    verified = ConsentedCatalogueFetcher(
        store=VerifiedCatalogueStore(tmp_path / "guided-state"),
        keyring=keyring,
        urlopen=StaticCatalogueHTTP(raw_catalogue),
        now=lambda: NOW,
    ).fetch(
        CatalogueFetchConsent(
            catalogue_url="https://heydex.ai/catalogue/dex-lens/v2.json",
            requested_at=NOW,
            statement=CONSENT_STATEMENT,
        )
    )
    journey = ConciergeJourney(
        permission=_permission(),
        collector=_fallback,
        job_store=InspectionJobStore(tmp_path / "guided-jobs"),
        now=lambda: NOW,
    )
    journey.approve()
    export_text = " ".join(
        (host_root / "bounded-export.txt").read_text(encoding="utf-8").split()
    )
    journey.add_fallback_evidence(
        FallbackEvidence(
            label="guided fixture export",
            level=EvidenceLevel.SUPPORTED,
            detail=export_text[:480],
            reference="export:guided-host#sha256=test-fixture",
            probe_id="guided-export",
        )
    )
    journey.continue_fallback()
    draft = journey.add_job(
        title="Review my work safely",
        situation="When the host cannot be deeply inspected",
        desired_outcome="The person still gets a bounded local brief",
    )
    journey.confirm_job(
        draft.job_id,
        success_evidence=("the next action is recorded",),
        privacy_limits=("stay within the supplied export",),
        approval_limits=("ask before external action",),
        autonomy_limits=("do not change files",),
        importance="medium",
        cadence="weekly",
        confirmed_at=NOW,
    )
    journey.diagnose()
    journey.record_catalogue_fetch(verified)
    journey.open_catalogue_shelf()
    first = journey.catalogue_shelf[0]
    journey.select_catalogue_brief(
        capability_id=first.capability_id,
        job_id=first.matched_job_ids[0],
    )
    return journey.catalogue_brief_markdown


def test_section6_local_golden_path_scaffold_covers_three_host_fixtures(
    tmp_path: Path,
) -> None:
    minimal = HOST_FIXTURE_ROOT / "minimal-claude"
    customised = HOST_FIXTURE_ROOT / "customised-claude"
    guided = HOST_FIXTURE_ROOT / "guided-export"
    assert (minimal / "CLAUDE.md").is_file()
    assert (customised / "CLAUDE.md").is_file()
    assert (customised / ".claude" / "skills" / "daily-plan" / "SKILL.md").is_file()
    assert (guided / "bounded-export.txt").is_file()

    briefs = (
        _brief_from_deep_host(minimal, tmp_path),
        _brief_from_deep_host(customised, tmp_path),
        _brief_from_guided_host(guided, tmp_path),
    )

    assert all("# Portable Brief:" in brief for brief in briefs)
    assert all("This is guidance only" in brief for brief in briefs)
    assert all("does not grant permission to read, write, send" in brief for brief in briefs)


def test_section6_evidence_pack_names_live_gates_that_are_not_proven_yet() -> None:
    text = EVIDENCE_PACK.read_text(encoding="utf-8")

    assert "Status: PREPARED, NOT PASSED" in text
    assert "real heydex.ai catalogue URL fetch" in text
    assert "subscribed-posture packet-level egress" in text
    assert "Dave signing-key ceremony" in text
