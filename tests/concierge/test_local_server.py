"""M3 local browser concierge: secure doorway and read-only stages 1-6."""

from __future__ import annotations

import http.client
import inspect
import tempfile
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from tests.adapters.claude_code.fixture_helpers import tree_digests

from capability_exchange.adapter import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.adapters.claude_code.containment import contained_inspection
from capability_exchange.concierge.server import ConciergeServer, new_session
from capability_exchange.evidence import EvidenceItem, EvidenceState

COLLECTED_AT = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)


def item(reference: str) -> EvidenceItem:
    return EvidenceItem(
        state=EvidenceState.OBSERVED,
        captured_at=COLLECTED_AT,
        reference=reference,
    )


def envelope() -> AdapterResultEnvelope:
    return AdapterResultEnvelope(
        adapter_id="claude-code-local",
        contract_version="0.1.0",
        collected_at=COLLECTED_AT,
        probes=(
            ProbeResult(
                probe_id="instructions-present",
                health=InstrumentHealth.HEALTHY,
                evidence=(item("file:claude-md#snap:k1"),),
            ),
            ProbeResult(
                probe_id="skills-present",
                health=InstrumentHealth.HEALTHY,
                evidence=(item("file:skills#snap:k2"),),
            ),
        ),
    )


class RunningServer(AbstractContextManager["RunningServer"]):
    def __init__(
        self,
        collector: Callable[..., AdapterResultEnvelope],
        *,
        approved_root: Path | None = None,
    ) -> None:
        self.calls = 0
        self.tempdir = tempfile.TemporaryDirectory()
        self.approved_root = approved_root or Path(self.tempdir.name) / "approved"
        self.approved_root.mkdir(parents=True, exist_ok=True)

        def counted_collector(
            cancel_event: threading.Event | None = None,
        ) -> AdapterResultEnvelope:
            self.calls += 1
            if inspect.signature(collector).parameters:
                return collector(cancel_event)
            return collector()

        self.session = new_session(
            approved_roots=(self.approved_root,),
            collector=counted_collector,
            now=lambda: COLLECTED_AT,
        )
        self.server = ConciergeServer(("127.0.0.1", 0), self.session)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.cookie = ""

    def __enter__(self) -> RunningServer:
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tempdir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], str]:
        merged = {"Host": f"127.0.0.1:{self.server.server_port}"}
        if self.cookie:
            merged["Cookie"] = self.cookie
        if headers:
            merged.update(headers)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request(method, path, body=body, headers=merged)
        response = conn.getresponse()
        payload = response.read().decode("utf-8", "replace")
        result_headers = {key.lower(): value for key, value in response.getheaders()}
        if "set-cookie" in result_headers:
            self.cookie = result_headers["set-cookie"].split(";", 1)[0]
        conn.close()
        return response.status, result_headers, payload

    def bootstrap(self) -> str:
        status, headers, _ = self.request("GET", f"/?token={self.session.bootstrap_token}")
        assert status == 303
        assert headers["location"] == "/session"
        status, _, html = self.request("GET", "/session")
        assert status == 200
        return html

    def post(self, path: str, body: str = "") -> tuple[int, dict[str, str], str]:
        return self.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.origin,
                "X-CSRF-Token": self.session.csrf_token,
            },
        )


class TestTrustedDoorway:
    def test_permission_page_renders_before_any_collection(self) -> None:
        with RunningServer(envelope) as running:
            html = running.bootstrap()
            assert running.calls == 0
            assert "Inspection permission" in html
            assert "Nothing has been scanned yet" in html
            assert "Capability Map" not in html

    def test_bootstrap_token_is_single_use(self) -> None:
        with RunningServer(envelope) as running:
            assert running.request("GET", f"/?token={running.session.bootstrap_token}")[0] == 303
            status, _, body = running.request(
                "GET", f"/?token={running.session.bootstrap_token}"
            )
            assert status == 403
            assert "expired or already used" in body

    def test_dns_rebinding_host_is_rejected(self) -> None:
        with RunningServer(envelope) as running:
            status, _, body = running.request(
                "GET",
                f"/?token={running.session.bootstrap_token}",
                headers={"Host": f"example.test:{running.server.server_port}"},
            )
            assert status == 403
            assert "host is not trusted" in body


class TestSessionSecurity:
    def test_post_requires_csrf_and_origin(self) -> None:
        with RunningServer(envelope) as running:
            running.bootstrap()
            assert running.request("POST", "/approve", headers={"Origin": running.origin})[
                0
            ] == 403
            assert running.request(
                "POST",
                "/approve",
                headers={"X-CSRF-Token": running.session.csrf_token},
            )[0] == 403
            assert running.request(
                "POST",
                "/approve",
                headers={
                    "Origin": "http://evil.test",
                    "X-CSRF-Token": running.session.csrf_token,
                },
            )[0] == 403

    def test_decline_exits_without_collection(self) -> None:
        with RunningServer(envelope) as running:
            running.bootstrap()
            status, _, body = running.post("/decline")
            assert status == 200
            assert "Session closed" in body
            assert running.calls == 0


class TestStagesOneToSix:
    def test_collection_starts_only_after_approval(self) -> None:
        with RunningServer(envelope) as running:
            running.bootstrap()
            status, _, body = running.post("/approve")
            assert status == 200
            assert running.calls == 1
            assert "Confirm your Job Map" in body
            assert "Possible job" in body
            assert "Capability Map" not in body

    def test_browser_form_csrf_token_is_accepted(self) -> None:
        with RunningServer(envelope) as running:
            running.bootstrap()
            status, _, body = running.request(
                "POST",
                "/approve",
                body=f"csrf_token={running.session.csrf_token}",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": running.origin,
                },
            )
            assert status == 200
            assert "Confirm your Job Map" in body

    def test_diagnosis_is_hidden_until_job_confirmation(self) -> None:
        with RunningServer(envelope) as running:
            running.bootstrap()
            running.post("/approve")
            status, _, body = running.post(
                "/confirm-jobs",
                body="job_id=instruction-guided-work&job_id=recurring-skill-workflows",
            )
            assert status == 400
            assert "full Success Contract" in body
            assert "Capability Map" not in body

    def test_full_success_contract_confirmation_precedes_diagnosis(self) -> None:
        with RunningServer(envelope) as running:
            running.bootstrap()
            status, _, body = running.post("/approve")
            assert status == 200
            assert 'action="/jobs/confirm"' in body
            assert 'action="/diagnose"' not in body
            assert "Capability Map" not in body

            status, _, body = running.post(
                "/jobs/confirm",
                body=urlencode(
                    {
                        "job_id": "instruction-guided-work",
                        "success_evidence": "instruction-guided output is ready",
                        "privacy_limits": "stay in the approved scope",
                        "approval_limits": "ask before any external action",
                        "autonomy_limits": "do not change files",
                        "importance": "medium",
                        "cadence": "weekly",
                    }
                ),
            )
            assert status == 200
            assert "Capability Map" not in body
            assert 'action="/diagnose"' not in body
            assert "instruction-guided-work" not in running.session.journey.job_ids

            status, _, body = running.post(
                "/jobs/discard",
                body=urlencode({"job_id": "recurring-skill-workflows"}),
            )
            assert status == 200
            assert "recurring-skill-workflows" not in running.session.journey.job_ids
            assert 'action="/diagnose"' in body

            status, _, body = running.post("/diagnose")
            assert status == 200
            assert "Capability Map" in body
            assert "Your job: instruction-guided-work" in body
            assert "overall score" not in body.lower()

    def test_real_contained_full_journey_writes_nothing_to_approved_root(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "claude-system"
        root.mkdir()
        (root / "CLAUDE.md").write_text(
            "Use the saved instructions for the weekly review.", encoding="utf-8"
        )
        before = tree_digests(root)

        def collect(cancel_event: threading.Event) -> AdapterResultEnvelope:
            return contained_inspection(
                [str(root)], cancel_event=cancel_event
            ).envelope

        with RunningServer(collect, approved_root=root) as running:
            running.bootstrap()
            status, _, body = running.post("/approve")
            assert status == 200
            assert "instruction-guided-work" in body
            status, _, _ = running.post(
                "/jobs/confirm",
                body=urlencode(
                    {
                        "job_id": "instruction-guided-work",
                        "success_evidence": "weekly review follows the instructions",
                        "privacy_limits": "stay inside the approved root",
                        "approval_limits": "ask before external action",
                        "autonomy_limits": "do not change files",
                        "importance": "medium",
                        "cadence": "weekly",
                    }
                ),
            )
            assert status == 200
            status, _, body = running.post("/diagnose")
            assert status == 200
            assert "Capability Map" in body

        assert tree_digests(root) == before
