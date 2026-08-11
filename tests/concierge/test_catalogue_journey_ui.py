from __future__ import annotations

import http.client
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from tests.catalogue.test_bridge import _catalogue
from tests.concierge.test_catalogue_doorway import _confirm_only_job
from tests.concierge.test_local_server import envelope

from capability_exchange.boundary.deletion import run_deletion_path
from capability_exchange.catalogue.fetch import (
    CatalogueFetchResult,
    CatalogueFetchStatus,
)
from capability_exchange.catalogue.subscription import CatalogueSubscriptionStore
from capability_exchange.concierge.server import ConciergeServer, new_session
from capability_exchange.concierge.views import render_journey

NOW = datetime(2026, 8, 11, 18, 30, tzinfo=UTC)


class RecordingFetcher:
    def __init__(
        self,
        *,
        result_factory: Callable[[], CatalogueFetchResult] | None = None,
    ) -> None:
        self.calls = 0
        self.result_factory = result_factory or self.verified

    def verified(self) -> CatalogueFetchResult:
        return CatalogueFetchResult(
            status=CatalogueFetchStatus.VERIFIED,
            message="catalogue verified locally",
            catalog_version=2,
            verified=None,
            stale=None,
            fetched_at=NOW,
            catalogue=_catalogue(),
        )

    def fetch(self, consent) -> CatalogueFetchResult:
        self.calls += 1
        return self.result_factory()


def _session(tmp_path: Path, fetcher: RecordingFetcher | None = None):
    (tmp_path / "approved").mkdir(exist_ok=True)
    session = new_session(
        approved_roots=(tmp_path / "approved",),
        collector=envelope,
        now=lambda: NOW,
        catalogue_fetcher=fetcher or RecordingFetcher(),
        app_storage=tmp_path / "app-storage",
    )
    _confirm_only_job(session)
    session.diagnose()
    return session


def test_full_shelf_screen_has_picked_and_browse_sections_with_escaped_catalogue_text(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    result = CatalogueFetchResult(
        status=CatalogueFetchStatus.VERIFIED,
        message="catalogue verified locally",
        catalog_version=2,
        verified=None,
        stale=None,
        fetched_at=NOW,
        catalogue=_catalogue().model_copy(
            update={
                "capabilities": (
                    _catalogue().capabilities[0].model_copy(
                        update={"title": "<script>Memory</script>"}
                    ),
                    *_catalogue().capabilities[1:],
                )
            }
        ),
    )
    session.journey.record_catalogue_fetch(result)

    session.open_catalogue_shelf()
    html = render_journey(session.journey, session.csrf_token)

    assert session.journey.stage.value == "catalogue-shelf"
    assert "Dex capability shelf" in html
    assert "Picked for your confirmed jobs" in html
    assert "Browse the full catalogue" in html
    assert "&lt;script&gt;Memory&lt;/script&gt;" in html
    assert "<script>Memory</script>" not in html
    assert "Copy portable brief" not in html


def test_selected_capability_brief_screen_renders_copy_and_save_affordances(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    session.journey.record_catalogue_fetch(RecordingFetcher().verified())
    session.open_catalogue_shelf()

    session.select_catalogue_brief(
        {
            "capability_id": ["durable-memory-boost"],
            "job_id": [session.journey.catalogue_shelf[0].matched_job_ids[0]],
        }
    )
    html = render_journey(session.journey, session.csrf_token)

    assert session.journey.stage.value == "catalogue-brief"
    assert "Portable brief for your AI" in html
    assert "Copy portable brief" in html
    assert "Save portable brief" in html
    assert "# Portable Brief: Durable Memory Boost" in html
    assert "Do not treat this brief as proof the capability is live" in html
    assert "Apply approved change" not in html


def test_subscription_create_revoke_and_delete_path_remove_durable_state(
    tmp_path: Path,
) -> None:
    store = CatalogueSubscriptionStore(tmp_path / "app-storage")

    record = store.subscribe(
        catalogue_url="https://heydex.ai/catalogue/dex-lens/v2.json",
        now=NOW,
    )
    assert record.subscribed
    assert store.path.exists()

    store.revoke(now=NOW)

    assert store.load().subscribed is False
    assert not store.path.exists()

    store.subscribe(
        catalogue_url="https://heydex.ai/catalogue/dex-lens/v2.json",
        now=NOW,
    )
    removed = run_deletion_path("delete-lens-catalogue-subscription", tmp_path / "app-storage")
    assert removed == [tmp_path / "app-storage" / "lens-catalogue-v2-subscription.json"]
    assert store.load().subscribed is False


def test_subscribed_returning_run_fetches_once_and_prompts_look_or_park(
    tmp_path: Path,
) -> None:
    store = CatalogueSubscriptionStore(tmp_path / "app-storage")
    store.subscribe(
        catalogue_url="https://heydex.ai/catalogue/dex-lens/v2.json",
        now=NOW,
    )
    store.mark_seen(catalog_version=1, now=NOW)
    fetcher = RecordingFetcher()

    session = _session(tmp_path, fetcher)
    html = render_journey(session.journey, session.csrf_token)

    assert fetcher.calls == 1
    assert "Dex catalogue updates are available" in html
    assert "Last seen catalogue: 1" in html
    assert "New since: 2" in html
    assert "Look at updates" in html
    assert "Park this update" in html


def test_parked_catalogue_shift_suppresses_returning_prompt(tmp_path: Path) -> None:
    store = CatalogueSubscriptionStore(tmp_path / "app-storage")
    store.subscribe(
        catalogue_url="https://heydex.ai/catalogue/dex-lens/v2.json",
        now=NOW,
    )
    store.mark_seen(catalog_version=1, now=NOW)
    store.park(catalog_version=2, now=NOW)

    session = _session(tmp_path, RecordingFetcher())
    html = render_journey(session.journey, session.csrf_token)

    assert "Dex catalogue updates are available" not in html
    assert "Parked catalogue update: 2" in html


def test_stale_offline_catalogue_is_labelled_not_usable_but_browsable(
    tmp_path: Path,
) -> None:
    store = CatalogueSubscriptionStore(tmp_path / "app-storage")
    store.subscribe(
        catalogue_url="https://heydex.ai/catalogue/dex-lens/v2.json",
        now=NOW,
    )
    stale = CatalogueFetchResult(
        status=CatalogueFetchStatus.STALE_CACHE,
        message="offline catalogue fetch; showing last verified catalogue as stale",
        catalog_version=2,
        verified=None,
        stale=None,
        fetched_at=NOW,
        catalogue=_catalogue(),
    )
    session = _session(tmp_path, RecordingFetcher(result_factory=lambda: stale))

    html = render_journey(session.journey, session.csrf_token)

    assert "Catalogue is stale/offline" in html
    assert "not treated as fresh or live" in html
    assert "Dex capability shelf" in html


class RunningCatalogueServer(AbstractContextManager["RunningCatalogueServer"]):
    def __init__(self, tmp_path: Path) -> None:
        self.session = _session(tmp_path)
        self.session.journey.record_catalogue_fetch(RecordingFetcher().verified())
        self.session.open_catalogue_shelf()
        self.server = ConciergeServer(("127.0.0.1", 0), self.session)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.cookie = f"dex_lens_session={self.session.session_token}"

    def __enter__(self):
        import threading

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def post(
        self,
        path: str,
        body: dict[str, str],
        *,
        csrf: str | None = None,
    ) -> tuple[int, str]:
        payload = urlencode(body)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request(
            "POST",
            path,
            body=payload,
            headers={
                "Host": f"127.0.0.1:{self.server.server_port}",
                "Cookie": self.cookie,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.origin,
                "X-CSRF-Token": csrf or "",
            },
        )
        response = conn.getresponse()
        text = response.read().decode("utf-8", "replace")
        status = response.status
        conn.close()
        return status, text

    def post_raw(
        self,
        path: str,
        body: dict[str, str],
        *,
        csrf: str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        payload = urlencode(body)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request(
            "POST",
            path,
            body=payload,
            headers={
                "Host": f"127.0.0.1:{self.server.server_port}",
                "Cookie": self.cookie,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.origin,
                "X-CSRF-Token": csrf or "",
            },
        )
        response = conn.getresponse()
        text = response.read().decode("utf-8", "replace")
        status = response.status
        headers = {key.lower(): value for key, value in response.getheaders()}
        conn.close()
        return status, headers, text


def test_catalogue_forms_require_csrf(tmp_path: Path) -> None:
    with RunningCatalogueServer(tmp_path) as running:
        status, body = running.post(
            "/catalogue/brief",
            {
                "capability_id": "durable-memory-boost",
                "job_id": running.session.journey.catalogue_shelf[0].matched_job_ids[0],
            },
        )
        assert status == 403
        assert "session security checks" in body

    with RunningCatalogueServer(tmp_path) as running:
        status, body = running.post(
            "/catalogue/brief",
            {
                "capability_id": "durable-memory-boost",
                "job_id": running.session.journey.catalogue_shelf[0].matched_job_ids[0],
            },
            csrf=running.session.csrf_token,
        )
        assert status == 200
        assert "Portable brief for your AI" in body


def test_portable_brief_save_downloads_exact_markdown_without_script(
    tmp_path: Path,
) -> None:
    with RunningCatalogueServer(tmp_path) as running:
        capability_id = "durable-memory-boost"
        job_id = running.session.journey.catalogue_shelf[0].matched_job_ids[0]
        status, body = running.post(
            "/catalogue/brief",
            {
                "capability_id": capability_id,
                "job_id": job_id,
            },
            csrf=running.session.csrf_token,
        )
        assert status == 200
        assert "Select the text above and copy it for your AI." in body
        assert "Copy portable brief</button>" not in body

        status, headers, markdown = running.post_raw(
            "/catalogue/brief/download",
            {},
            csrf=running.session.csrf_token,
        )

        assert status == 200
        assert headers["content-type"] == "text/markdown; charset=utf-8"
        assert (
            headers["content-disposition"]
            == 'attachment; filename="dex-brief-durable-memory-boost.md"'
        )
        assert markdown == running.session.journey.catalogue_brief_markdown
