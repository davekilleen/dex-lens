#!/usr/bin/env python3
"""Section-6 live bridge proof against the real heydex.ai catalogue URL."""

from __future__ import annotations

import argparse
import json
import os
import re
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
    load_catalogue_release_expectation,
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
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


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
        try:
            return self._response.__exit__(*args)
        finally:
            self._entered = None

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
    if expected.catalog_version <= 1:
        raise RuntimeError(
            "subscription update proof requires a catalogue version after version 1"
        )
    first_counter = CountedUrlOpen(expected)
    first = new_session(
        approved_roots=(HOST_FIXTURE_ROOT / "minimal-claude",),
        collector=envelope,
        catalogue_fetcher=_fetcher(tmp_path, "live-subscription-first", first_counter),
        app_storage=tmp_path / "live-subscription-manual-app-storage",
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

    app_storage = tmp_path / "live-subscription-app-storage"
    store = CatalogueSubscriptionStore(app_storage)
    store.subscribe(catalogue_url=CATALOGUE_URL, now=NOW)
    store.mark_seen(catalog_version=expected.catalog_version - 1, now=NOW)

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
    parked_record = store.load()

    parked_counter = CountedUrlOpen(expected)
    parked = new_session(
        approved_roots=(HOST_FIXTURE_ROOT / "minimal-claude",),
        collector=envelope,
        catalogue_fetcher=_fetcher(tmp_path, "live-subscription-parked", parked_counter),
        app_storage=app_storage,
        catalogue_subscription_store=store,
    )
    _confirm_session_jobs(parked, marker="live subscription parked returning run")
    parked_html = render_journey(parked.journey, parked.csrf_token)

    parked.revoke_catalogue_updates()
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
        "subscribed_prompt_rendered": "Dex catalogue updates are available"
        in subscribed_html,
        "parked_version": parked_record.parked_catalog_version,
        "parked_returning_fetch_requests": parked_counter.count,
        "parked_prompt_suppressed": "Dex catalogue updates are available"
        not in parked_html
        and f"Parked catalogue update: {expected.catalog_version}" in parked_html,
        "unsubscribed_returning_fetch_requests": unsubscribed_counter.count,
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


def _resolve_release_expectation(args: argparse.Namespace) -> CatalogueReleaseExpectation:
    direct_values = {
        "core_release": args.expected_core_release,
        "key_id": args.expected_key_id,
        "raw_sha256": args.expected_sha256,
        "catalog_version": args.expected_catalog_version,
        "capability_count": args.expected_capability_count,
        "job_count": args.expected_job_count,
        "capability_ids": args.expected_capability_ids,
    }
    supplied = {name for name, value in direct_values.items() if value is not None}
    if args.expectation_manifest is not None:
        if supplied:
            raise ValueError(
                "expectation manifest cannot be combined with direct release expectations"
            )
        return load_catalogue_release_expectation(args.expectation_manifest)
    missing = sorted(set(direct_values) - supplied)
    if missing:
        raise ValueError(
            "direct release expectations must supply every field; "
            f"missing={missing}"
        )
    return CatalogueReleaseExpectation(
        core_release=direct_values["core_release"],
        key_id=direct_values["key_id"],
        raw_sha256=direct_values["raw_sha256"],
        catalog_version=direct_values["catalog_version"],
        capability_count=direct_values["capability_count"],
        job_count=direct_values["job_count"],
        capability_ids=tuple(
            item.strip() for item in direct_values["capability_ids"].split(",")
        ),
    )


def _expected_evidence(expected: CatalogueReleaseExpectation) -> dict[str, Any]:
    return {
        "core_release": expected.core_release,
        "key_id": expected.key_id,
        "raw_sha256": expected.raw_sha256,
        "catalog_version": expected.catalog_version,
        "capability_count": expected.capability_count,
        "job_count": expected.job_count,
        "capability_ids": list(expected.capability_ids),
    }


def _stop_capture(
    capture: tuple[subprocess.Popen[str], Any] | None,
) -> tuple[bool, str]:
    if capture is None:
        return False, ""
    process, stream = capture
    try:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            _, capture_stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            _, capture_stderr = process.communicate()
        return process.returncode == 0, capture_stderr
    except BaseException:
        try:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        except BaseException:
            pass
        raise
    finally:
        stream.close()


def _journey_failure(journey: dict[str, Any]) -> dict[str, str] | None:
    subscription = journey["subscription"]
    if subscription["manual_fetch_requests"] != 1:
        return {
            "type": "JourneyProofFailure",
            "message": "manual consent run did not make exactly one fetch",
        }
    if subscription["subscribed_returning_fetch_requests"] != 1:
        return {
            "type": "JourneyProofFailure",
            "message": "subscribed returning run did not make exactly one fetch",
        }
    if not subscription["subscribed_prompt_rendered"]:
        return {
            "type": "JourneyProofFailure",
            "message": "newer catalogue prompt was not rendered",
        }
    if subscription["parked_version"] != journey["catalog_version"]:
        return {
            "type": "JourneyProofFailure",
            "message": "parked catalogue version did not match the live version",
        }
    if subscription["parked_returning_fetch_requests"] != 1:
        return {
            "type": "JourneyProofFailure",
            "message": "parked returning run did not fetch once",
        }
    if not subscription["parked_prompt_suppressed"]:
        return {
            "type": "JourneyProofFailure",
            "message": "parked catalogue prompt was not suppressed",
        }
    if subscription["unsubscribed_returning_fetch_requests"] != 0:
        return {
            "type": "JourneyProofFailure",
            "message": "unsubscribed returning run made a fetch",
        }
    if subscription["subscribed_after_revoke"]:
        return {
            "type": "JourneyProofFailure",
            "message": "catalogue subscription survived revocation",
        }
    if journey["minimal_fetch_requests"] != 1 or journey["customised_fetch_requests"] != 1:
        return {
            "type": "JourneyProofFailure",
            "message": "consented host run did not make exactly one catalogue fetch",
        }
    if not journey["shelf_contains_expected_catalogue"] or not journey["briefs_non_identical"]:
        return {
            "type": "JourneyProofFailure",
            "message": "live journey did not satisfy section-6 shelf/brief proof",
        }
    if not all(
        journey[key]
        for key in (
            "minimal_brief_host_specific",
            "customised_brief_host_specific",
            "guided_brief_host_specific",
        )
    ):
        return {
            "type": "JourneyProofFailure",
            "message": "live journey briefs were not host-specific",
        }
    if not journey["tamper_refused"]:
        return {
            "type": "JourneyProofFailure",
            "message": "tampered live catalogue verified unexpectedly",
        }
    return None


def _build_identity() -> tuple[str, str]:
    """Return the reviewed source and actual execution commits, fail closed."""
    execution_commit = os.environ.get("DEX_LENS_BUILD_COMMIT")
    if not execution_commit:
        execution_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    source_commit = os.environ.get("DEX_LENS_SOURCE_COMMIT", execution_commit)
    if not _GIT_SHA.fullmatch(source_commit):
        raise ValueError("reviewed source commit must be an exact lowercase Git SHA")
    if not _GIT_SHA.fullmatch(execution_commit):
        raise ValueError("execution commit must be an exact lowercase Git SHA")
    return source_commit, execution_commit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--expectation-manifest", type=Path)
    parser.add_argument("--expected-core-release")
    parser.add_argument("--expected-key-id")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-catalog-version", type=int)
    parser.add_argument("--expected-capability-count", type=int)
    parser.add_argument("--expected-job-count", type=int)
    parser.add_argument(
        "--expected-capability-ids",
        help="Comma-separated complete capability id list in release order.",
    )
    parser.add_argument("--allow-no-packet", action="store_true")
    args = parser.parse_args()

    try:
        expected = _resolve_release_expectation(args)
    except ValueError as error:
        parser.error(str(error))

    if os.environ.get("DEX_LENS_SECTION6_LIVE") != "1":
        print("section-6 live proof requires DEX_LENS_SECTION6_LIVE=1", file=sys.stderr)
        return 2

    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    pcap = args.artifact_dir / "section6-live.pcap"
    capture: tuple[subprocess.Popen[str], Any] | None = None
    capture_ready = False
    capture_clean_exit = False
    capture_stderr = ""
    journey: dict[str, Any] | None = None
    failure: dict[str, str] | None = None
    source_commit = os.environ.get("DEX_LENS_SOURCE_COMMIT", "unavailable")
    execution_commit = os.environ.get("DEX_LENS_BUILD_COMMIT", "unavailable")
    try:
        source_commit, execution_commit = _build_identity()
        capture = _start_capture(pcap)
        if capture is not None:
            capture_ready = _capture_ready(capture[0])
        with tempfile.TemporaryDirectory(prefix="dex-section6-live-") as tmp:
            journey = _run_live_journey(Path(tmp), expected)
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            capture_clean_exit, capture_stderr = _stop_capture(capture)
        except Exception as error:
            if failure is None:
                failure = {"type": type(error).__name__, "message": str(error)}
    packet: dict[str, Any] = {}
    if capture_ready and pcap.is_file():
        try:
            packet = _packet_summary(pcap, capture_stderr)
        except Exception as error:
            if failure is None:
                failure = {"type": type(error).__name__, "message": str(error)}
    if failure is None:
        if journey is None:
            failure = {
                "type": "JourneyProofFailure",
                "message": "live journey returned no observation",
            }
        else:
            failure = _journey_failure(journey)
    if failure is None and capture_ready and capture_clean_exit:
        dropped_packets = packet.get("capture_packets_dropped")
        if type(dropped_packets) is not int or dropped_packets < 0:
            failure = {
                "type": "PacketProofFailure",
                "message": "packet capture dropped-packet count is unavailable",
            }
        elif dropped_packets > 0:
            failure = {
                "type": "PacketProofFailure",
                "message": f"packet capture dropped {dropped_packets} packet(s)",
            }
    if (
        failure is None
        and capture_ready
        and capture_clean_exit
        and packet.get("non_loopback_packet_count", 0) <= 0
    ):
        failure = {
            "type": "PacketProofFailure",
            "message": "packet capture did not record live egress",
        }

    if failure is not None:
        status = "failed"
        exit_code = 1
    elif not capture_ready or not capture_clean_exit:
        status = "journey-proven-packet-not-proven"
        exit_code = 0 if args.allow_no_packet else 2
    else:
        status = "proven"
        exit_code = 0

    evidence = {
        "schema_version": 1,
        "status": status,
        "commit": source_commit,
        "execution_commit": execution_commit,
        "run_id": f"section6-live-{uuid.uuid4().hex}",
        "expected": _expected_evidence(expected),
        "packet": {
            "capture_ready": capture_ready,
            "capture_clean_exit": capture_clean_exit,
            **packet,
        },
    }
    if journey is not None:
        evidence["journey"] = journey
    if failure is not None:
        evidence["failure"] = failure
    (args.artifact_dir / "section6-live-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if failure is not None:
        print(
            f"SECTION6 LIVE BRIDGE PROOF FAILED: {failure['type']}: {failure['message']}",
            file=sys.stderr,
        )
        return exit_code
    if exit_code == 2:
        print("section-6 packet evidence was not proven", file=sys.stderr)
        return exit_code
    if status == "journey-proven-packet-not-proven":
        print("SECTION6 LIVE JOURNEY PROVEN; packet capture not proven on this host")
        return exit_code
    print("SECTION6 LIVE BRIDGE PROOF PASSED")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
