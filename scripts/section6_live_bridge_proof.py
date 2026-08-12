#!/usr/bin/env python3
"""Section-6 live bridge proof against the real heydex.ai catalogue URL."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.concierge.test_fallback_e2e import _fallback, _permission  # noqa: E402
from tests.concierge.test_local_server import envelope  # noqa: E402
from tests.e2e.test_bridge_golden_path import (  # noqa: E402
    CATALOGUE_URL,
    HOST_FIXTURE_ROOT,
    _confirm_session_jobs,
)
from tests.egress.namespace_probe import (  # noqa: E402
    _capture_ready,
    _capture_statistics,
    _packet_endpoints,
    _tcpdump_lines,
)

from capability_exchange.catalogue.fetch import (  # noqa: E402
    CONSENT_STATEMENT,
    CatalogueFetchResult,
    CatalogueFetchStatus,
    ConsentedCatalogueFetcher,
)
from capability_exchange.catalogue.release_acceptance import (  # noqa: E402
    CatalogueReleaseExpectation,
    CatalogueReleaseObservation,
    assert_catalogue_release,
)
from capability_exchange.catalogue.subscription import CatalogueSubscriptionStore  # noqa: E402
from capability_exchange.catalogue.v2 import (  # noqa: E402
    CatalogueVerificationError,
    VerifiedCatalogueStore,
    default_keyring,
    verify_catalogue_envelope,
)
from capability_exchange.concierge.journey import (  # noqa: E402
    ConciergeJourney,
    FallbackEvidence,
)
from capability_exchange.concierge.server import new_session  # noqa: E402
from capability_exchange.concierge.views import render_journey  # noqa: E402
from capability_exchange.evidence import EvidenceLevel  # noqa: E402
from capability_exchange.jobs import InspectionJobStore  # noqa: E402

NOW = datetime(2026, 8, 12, 10, 45, tzinfo=UTC)


@dataclass
class CountedUrlOpen:
    expected: CatalogueReleaseExpectation
    count: int = 0
    urls: list[str] | None = None

    def __post_init__(self) -> None:
        self.urls = []

    def __call__(self, request: Request, *, timeout: float) -> object:
        self.count += 1
        assert self.urls is not None
        self.urls.append(request.full_url)
        return _ReleaseValidatingResponse(
            urlopen(request, timeout=timeout),
            self.expected,
        )


class _ReleaseValidatingResponse:
    """Validate the exact raw release bytes before a fetcher can consume them."""

    def __init__(
        self,
        response: object,
        expected: CatalogueReleaseExpectation,
    ) -> None:
        self._response = response
        self._entered: object | None = None
        self._expected = expected

    def __enter__(self) -> _ReleaseValidatingResponse:
        self._entered = self._response.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._response.__exit__(*args)

    def read(self) -> bytes:
        if self._entered is None:
            raise RuntimeError("catalogue response was read outside its context")
        raw = self._entered.read()
        verified = verify_catalogue_envelope(
            raw.decode("utf-8"),
            keyring=default_keyring(),
        )
        assert_catalogue_release(raw, verified, self._expected)
        return raw


def _read_live_catalogue(
    expected: CatalogueReleaseExpectation,
) -> tuple[bytes, object, CatalogueReleaseObservation]:
    with urlopen(CATALOGUE_URL, timeout=10) as response:
        raw = response.read()
    verified = verify_catalogue_envelope(
        raw.decode("utf-8"),
        keyring=default_keyring(),
    )
    observed = assert_catalogue_release(raw, verified, expected)
    return raw, verified, observed


def _fetcher(
    tmp_path: Path,
    name: str,
    counter: CountedUrlOpen,
) -> ConsentedCatalogueFetcher:
    return ConsentedCatalogueFetcher(
        store=VerifiedCatalogueStore(tmp_path / f"{name}-catalogue-store"),
        keyring=default_keyring(),
        urlopen=counter,
    )


def _live_deep_host_brief(
    host_root: Path,
    tmp_path: Path,
    expected: CatalogueReleaseExpectation,
) -> tuple[str, tuple[str, ...], int]:
    counter = CountedUrlOpen(expected)
    session = new_session(
        approved_roots=(host_root,),
        collector=envelope,
        catalogue_fetcher=_fetcher(tmp_path, host_root.name, counter),
        app_storage=tmp_path / f"{host_root.name}-app-storage",
    )
    marker = (
        "customised host with skills/hooks/subagents"
        if host_root.name == "customised-claude"
        else "minimal host with one CLAUDE.md"
    )
    _confirm_session_jobs(session, marker=marker)
    result = session.fetch_catalogue(
        {
            "catalogue_consent": [CONSENT_STATEMENT],
            "catalogue_url": [CATALOGUE_URL],
        }
    )
    if result.status is not CatalogueFetchStatus.VERIFIED or result.verified is None:
        raise RuntimeError(f"live catalogue fetch failed: {result.status} {result.message}")
    session.open_catalogue_shelf()
    first = session.journey.catalogue_shelf[0]
    session.select_catalogue_brief(
        {
            "capability_id": [first.capability_id],
            "job_id": [first.matched_job_ids[0]],
        }
    )
    return (
        session.journey.catalogue_brief_markdown,
        tuple(match.capability_id for match in session.journey.catalogue_shelf),
        counter.count,
    )


def _live_guided_brief(
    tmp_path: Path,
    expected: CatalogueReleaseExpectation,
) -> str:
    _raw, verified, _observed = _read_live_catalogue(expected)
    host_root = HOST_FIXTURE_ROOT / "guided-export"
    journey = ConciergeJourney(
        permission=_permission(),
        collector=_fallback,
        job_store=InspectionJobStore(tmp_path / "guided-live-jobs"),
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
    journey.record_catalogue_fetch(
        CatalogueFetchResult(
            status=CatalogueFetchStatus.VERIFIED,
            message="catalogue verified locally",
            catalog_version=verified.metadata.catalog_version,
            verified=verified,
            stale=None,
            fetched_at=NOW,
            catalogue=verified.catalogue,
        )
    )
    journey.open_catalogue_shelf()
    first = journey.catalogue_shelf[0]
    journey.select_catalogue_brief(
        capability_id=first.capability_id,
        job_id=first.matched_job_ids[0],
    )
    return journey.catalogue_brief_markdown

def _prove_subscription_postures(
    tmp_path: Path,
    expected: CatalogueReleaseExpectation,
) -> dict[str, Any]:
    app_storage = tmp_path / "live-subscription-app-storage"
    store = CatalogueSubscriptionStore(app_storage)

    first_counter = CountedUrlOpen(expected)
    first = new_session(
        approved_roots=(HOST_FIXTURE_ROOT / "minimal-claude",),
        collector=envelope,
        catalogue_fetcher=_fetcher(tmp_path, "live-subscription-first", first_counter),
        app_storage=app_storage,
        catalogue_subscription_store=store,
    )
    _confirm_session_jobs(first, marker="live subscription first run")
    first_result = first.fetch_catalogue(
        {
            "catalogue_consent": [CONSENT_STATEMENT],
            "catalogue_url": [CATALOGUE_URL],
        }
    )
    if first_result.status is not CatalogueFetchStatus.VERIFIED:
        raise RuntimeError("first live subscription fetch failed")
    first.subscribe_catalogue_updates({"catalogue_url": [CATALOGUE_URL]})
    first.look_catalogue_updates()

    subscribed_counter = CountedUrlOpen(expected)
    subscribed = new_session(
        approved_roots=(HOST_FIXTURE_ROOT / "minimal-claude",),
        collector=envelope,
        catalogue_fetcher=_fetcher(
            tmp_path, "live-subscription-returning", subscribed_counter
        ),
        app_storage=app_storage,
        catalogue_subscription_store=store,
    )
    _confirm_session_jobs(subscribed, marker="live subscription returning run")
    subscribed_html = render_journey(subscribed.journey, subscribed.csrf_token)
    subscribed.park_catalogue_updates()

    subscribed.revoke_catalogue_updates()
    unsubscribed_counter = CountedUrlOpen(expected)
    unsubscribed = new_session(
        approved_roots=(HOST_FIXTURE_ROOT / "minimal-claude",),
        collector=envelope,
        catalogue_fetcher=_fetcher(
            tmp_path, "live-subscription-unsubscribed", unsubscribed_counter
        ),
        app_storage=app_storage,
        catalogue_subscription_store=store,
    )
    _confirm_session_jobs(unsubscribed, marker="live subscription revoked run")

    return {
        "manual_fetch_requests": first_counter.count,
        "subscribed_returning_fetch_requests": subscribed_counter.count,
        "unsubscribed_returning_fetch_requests": unsubscribed_counter.count,
        "subscribed_prompt_rendered": "Dex catalogue updates are available"
        in subscribed_html,
        "parked_version": store.load().parked_catalog_version,
        "subscribed_after_revoke": store.load().subscribed,
    }


def _run_live_journey(
    tmp_path: Path,
    expected: CatalogueReleaseExpectation,
) -> dict[str, Any]:
    live_raw, verified, observed = _read_live_catalogue(expected)
    tampered = live_raw.decode("utf-8").replace("Daily Plan", "Daily Plan!", 1)
    try:
        verify_catalogue_envelope(tampered, keyring=default_keyring())
    except CatalogueVerificationError:
        tamper_refused = True
    else:
        tamper_refused = False

    minimal_brief, minimal_shelf, minimal_requests = _live_deep_host_brief(
        HOST_FIXTURE_ROOT / "minimal-claude", tmp_path, expected
    )
    customised_brief, customised_shelf, customised_requests = _live_deep_host_brief(
        HOST_FIXTURE_ROOT / "customised-claude", tmp_path, expected
    )
    guided_brief = _live_guided_brief(tmp_path, expected)
    subscription = _prove_subscription_postures(tmp_path, expected)

    return {
        "live_url": CATALOGUE_URL,
        "core_release": observed.core_release,
        "key_id": observed.key_id,
        "raw_sha256": observed.raw_sha256,
        "catalog_version": observed.catalog_version,
        "capability_ids": list(observed.capability_ids),
        "job_count": observed.job_count,
        "tamper_refused": tamper_refused,
        "minimal_fetch_requests": minimal_requests,
        "customised_fetch_requests": customised_requests,
        "minimal_shelf_count": len(minimal_shelf),
        "customised_shelf_count": len(customised_shelf),
        "shelf_contains_expected_catalogue": len(minimal_shelf)
        == expected.capability_count
        and len(customised_shelf) == expected.capability_count
        and set(minimal_shelf) == set(expected.capability_ids)
        and set(customised_shelf) == set(expected.capability_ids),
        "briefs_non_identical": len({minimal_brief, customised_brief, guided_brief}) == 3,
        "minimal_brief_host_specific": "minimal host with one CLAUDE.md" in minimal_brief,
        "customised_brief_host_specific": "customised host with skills/hooks/subagents"
        in customised_brief,
        "guided_brief_host_specific": "When the host cannot be deeply inspected"
        in guided_brief,
        "subscription": subscription,
    }


def _start_capture(pcap: Path) -> tuple[subprocess.Popen[str], Any] | None:
    tcpdump = shutil.which("tcpdump")
    if tcpdump is None:
        return None
    try:
        stream = pcap.open("wb")
    except OSError:
        return None
    try:
        process = subprocess.Popen(
            [
                tcpdump,
                "-i",
                "any",
                "-nn",
                "-U",
                "--immediate-mode",
                "-s",
                "0",
                "-Z",
                "root",
                "-w",
                "-",
            ],
            stdout=stream,
            stderr=subprocess.PIPE,
            text=True,
        )
    except BaseException:
        stream.close()
        raise
    return process, stream


def _packet_summary(pcap: Path, capture_stderr: str) -> dict[str, Any]:
    packet_lines = _tcpdump_lines(pcap) if pcap.is_file() else []
    dns_lines = _tcpdump_lines(pcap, "(udp or tcp) and port 53") if pcap.is_file() else []
    endpoints, unparsed = _packet_endpoints(packet_lines)
    loopbacks = {"127.0.0.1", "::1"}
    non_loopback_count = sum(
        1
        for source, destination in endpoints
        if source not in loopbacks or destination not in loopbacks
    )
    return {
        "packet_count": len(packet_lines),
        "dns_packet_count": len(dns_lines),
        "non_loopback_packet_count": non_loopback_count,
        "unparsed_packet_count": len(unparsed),
        **_capture_statistics(capture_stderr),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--expected-core-release", required=True)
    parser.add_argument("--expected-key-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-catalog-version", type=int, required=True)
    parser.add_argument("--expected-capability-count", type=int, required=True)
    parser.add_argument("--expected-job-count", type=int, required=True)
    parser.add_argument(
        "--expected-capability-ids",
        required=True,
        help="Comma-separated complete capability id list in release order.",
    )
    parser.add_argument("--allow-no-packet", action="store_true")
    args = parser.parse_args()

    try:
        expected = CatalogueReleaseExpectation(
            core_release=args.expected_core_release,
            key_id=args.expected_key_id,
            raw_sha256=args.expected_sha256,
            catalog_version=args.expected_catalog_version,
            capability_count=args.expected_capability_count,
            job_count=args.expected_job_count,
            capability_ids=tuple(
                item.strip() for item in args.expected_capability_ids.split(",")
            ),
        )
    except ValueError as error:
        parser.error(str(error))

    if os.environ.get("DEX_LENS_SECTION6_LIVE") != "1":
        print("section-6 live proof requires DEX_LENS_SECTION6_LIVE=1", file=sys.stderr)
        return 2

    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    pcap = args.artifact_dir / "section6-live.pcap"
    capture = _start_capture(pcap)
    capture_ready = False
    capture_stderr = ""
    if capture is not None:
        capture_ready = _capture_ready(capture[0])

    with tempfile.TemporaryDirectory(prefix="dex-section6-live-") as tmp:
        journey = _run_live_journey(Path(tmp), expected)

    capture_clean_exit = False
    if capture is not None:
        process, stream = capture
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            _, capture_stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            _, capture_stderr = process.communicate()
        stream.close()
        capture_clean_exit = process.returncode == 0
    packet = _packet_summary(pcap, capture_stderr) if capture_ready and pcap.is_file() else {}
    commit = os.environ.get("DEX_LENS_BUILD_COMMIT")
    if not commit:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()

    evidence = {
        "schema_version": 1,
        "status": "proven"
        if capture_ready and capture_clean_exit
        else "journey-proven-packet-not-proven",
        "commit": commit,
        "run_id": f"section6-live-{uuid.uuid4().hex}",
        "journey": journey,
        "packet": {
            "capture_ready": capture_ready,
            "capture_clean_exit": capture_clean_exit,
            **packet,
        },
    }
    (args.artifact_dir / "section6-live-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if journey["subscription"]["subscribed_returning_fetch_requests"] != 1:
        print("subscribed returning run did not make exactly one fetch", file=sys.stderr)
        return 1
    if journey["subscription"]["unsubscribed_returning_fetch_requests"] != 0:
        print("unsubscribed returning run made a fetch", file=sys.stderr)
        return 1
    if (
        not journey["shelf_contains_expected_catalogue"]
        or not journey["briefs_non_identical"]
    ):
        print("live journey did not satisfy section-6 shelf/brief proof", file=sys.stderr)
        return 1
    if not journey["tamper_refused"]:
        print("tampered live catalogue verified unexpectedly", file=sys.stderr)
        return 1
    if not capture_ready or not capture_clean_exit:
        if args.allow_no_packet:
            print("SECTION6 LIVE JOURNEY PROVEN; packet capture not proven on this host")
            return 0
        print("section-6 packet evidence was not proven", file=sys.stderr)
        return 2
    if evidence["packet"].get("non_loopback_packet_count", 0) <= 0:
        print("packet capture did not record live egress", file=sys.stderr)
        return 1
    print("SECTION6 LIVE BRIDGE PROOF PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
