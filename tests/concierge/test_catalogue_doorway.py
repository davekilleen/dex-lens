from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.concierge.test_local_server import envelope

from capability_exchange.catalogue.fetch import CatalogueFetchResult, CatalogueFetchStatus
from capability_exchange.concierge.server import new_session
from capability_exchange.concierge.views import render_journey

NOW = datetime(2026, 8, 11, 15, 30, tzinfo=UTC)


class RecordingFetcher:
    def __init__(self, status: CatalogueFetchStatus = CatalogueFetchStatus.VERIFIED) -> None:
        self.calls = 0
        self.status = status

    def fetch(self, consent) -> CatalogueFetchResult:
        self.calls += 1
        return CatalogueFetchResult(
            status=self.status,
            message="catalogue status recorded",
            catalog_version=7 if self.status is not CatalogueFetchStatus.OFFLINE else None,
            verified=None,
            stale=None,
            fetched_at=NOW,
        )


def _confirm_only_job(session) -> None:
    if session.journey.stage.value == "permission":
        session.approve_scope_and_collect()
    for job_id in session.journey.job_ids:
        session.confirm_job(
            {
                "job_id": [job_id],
                "success_evidence": ["the confirmed outcome is visible"],
                "privacy_limits": ["stay local"],
                "approval_limits": ["ask first"],
                "autonomy_limits": ["do not change files"],
                "importance": ["medium"],
                "cadence": ["weekly"],
            }
        )


def test_catalogue_button_appears_after_job_confirmation_without_fetching(tmp_path: Path) -> None:
    fetcher = RecordingFetcher()
    session = new_session(
        approved_roots=(tmp_path,),
        collector=envelope,
        now=lambda: NOW,
        catalogue_fetcher=fetcher,
    )

    session.approve_scope_and_collect()
    before_confirmation = render_journey(session.journey, session.csrf_token)
    assert "Fetch public Dex catalogue" not in before_confirmation

    _confirm_only_job(session)
    after_confirmation = render_journey(session.journey, session.csrf_token)

    assert fetcher.calls == 0
    assert "Fetch public Dex catalogue" in after_confirmation
    assert "public signed Dex catalogue" in after_confirmation
    assert "system is sent to Dex" in after_confirmation
    assert "https://heydex.ai/catalogue/dex-lens/v2.json" in after_confirmation


def test_catalogue_button_appears_on_capability_map_without_fetching(
    tmp_path: Path,
) -> None:
    fetcher = RecordingFetcher()
    session = new_session(
        approved_roots=(tmp_path,),
        collector=envelope,
        now=lambda: NOW,
        catalogue_fetcher=fetcher,
    )
    _confirm_only_job(session)

    session.diagnose()
    capability_map_page = render_journey(session.journey, session.csrf_token)

    assert fetcher.calls == 0
    assert "Capability Map" in capability_map_page
    assert "Fetch public Dex catalogue" in capability_map_page
    assert "Exact URL Lens will request" in capability_map_page
    assert "https://heydex.ai/catalogue/dex-lens/v2.json" in capability_map_page


def test_catalogue_fetch_requires_explicit_consent_statement(tmp_path: Path) -> None:
    fetcher = RecordingFetcher()
    session = new_session(
        approved_roots=(tmp_path,),
        collector=envelope,
        now=lambda: NOW,
        catalogue_fetcher=fetcher,
    )
    _confirm_only_job(session)

    result = session.fetch_catalogue({"catalogue_consent": ["wrong"]})

    assert result.status is CatalogueFetchStatus.REFUSED
    assert fetcher.calls == 0


def test_catalogue_fetch_records_state_when_explicitly_called(tmp_path: Path) -> None:
    fetcher = RecordingFetcher(CatalogueFetchStatus.STALE_CACHE)
    session = new_session(
        approved_roots=(tmp_path,),
        collector=envelope,
        now=lambda: NOW,
        catalogue_fetcher=fetcher,
    )
    _confirm_only_job(session)

    result = session.fetch_catalogue(
        {
            "catalogue_consent": ["fetch-public-signed-dex-catalogue"],
            "catalogue_url": ["https://heydex.ai/catalogue/dex-lens/v2.json"],
        }
    )
    page = render_journey(session.journey, session.csrf_token)

    assert fetcher.calls == 1
    assert result.status is CatalogueFetchStatus.STALE_CACHE
    assert session.journey.catalogue_fetch_result is result
    assert "Catalogue is stale" in page
