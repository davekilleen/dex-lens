"""Child process for :mod:`tests.egress.network_harness`.

This process is intentionally tiny and only runs under ``unshare --net``.
It enables loopback, records packets with tcpdump, drives the complete local
concierge journey, and writes a no-secret evidence summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socketserver
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from tests.adapters.claude_code.fixture_helpers import tree_digests
from tests.concierge.test_local_server import RunningServer
from tests.egress.harness import EGRESS_CANARIES, build_canary_system
from tests.fixtures.hostile.catalog import assert_no_canary_leak, derivations_of

from capability_exchange.adapters.claude_code.containment import contained_inspection


class _Proxy(socketserver.BaseRequestHandler):
    requests: list[str] = []

    def handle(self) -> None:  # pragma: no cover - only called on a failed egress
        # Keep only a count marker: a failed proxy route must not copy a
        # private request into the evidence artifact that CI uploads.
        self.requests.append(f"request-received:{len(self.request.recv(4096))}")


def _tcpdump_lines(pcap: Path, expression: str | None = None) -> list[str]:
    command = [shutil.which("tcpdump") or "tcpdump", "-nn", "-r", str(pcap)]
    if expression:
        command.append(expression)
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "tcpdump could not read the capture")
    return [
        line
        for line in result.stdout.splitlines()
        if line and not line.startswith("reading from")
    ]


def _packet_endpoints(lines: list[str]) -> list[tuple[str, str]]:
    endpoints: list[tuple[str, str]] = []
    # tcpdump -nn's IPv4 form is stable: ``IP 127.0.0.1.123 > 127.0.0.1.456``.
    pattern = re.compile(r"\bIP\s+([^ ]+)\s+>\s+([^ ]+)")
    for line in lines:
        match = pattern.search(line)
        if match:
            source = match.group(1).rsplit(".", 1)[0]
            destination = match.group(2).rsplit(".", 1)[0]
            endpoints.append((source, destination))
    return endpoints


def _run_journey() -> tuple[list[str], list[str], list[str]]:
    run_canary = f"m3-unique-canary-{uuid.uuid4().hex}"
    pages: list[str] = []
    base = Path(tempfile.mkdtemp(prefix="dex-m3-fixture-"))
    root = build_canary_system(base)
    # The unique marker is intentionally in a collected basename and is
    # therefore covered by both raw and derivation checks.
    (root / "CLAUDE.md").write_text(f"{run_canary}\n")
    canaries = [*EGRESS_CANARIES, run_canary]
    before = tree_digests(root)

    def collect(cancel_event: threading.Event):
        return contained_inspection([str(root)], cancel_event=cancel_event).envelope

    with RunningServer(collect, approved_root=root) as running:
        pages.append(running.bootstrap())
        status, _, body = running.post("/approve")
        if status != 200:
            raise AssertionError(f"approval failed: {status}")
        pages.append(body)
        running.wait_for_collection()
        status, _, body = running.request("GET", "/session")
        if status != 200:
            raise AssertionError(f"session failed: {status}")
        pages.append(body)
        for job_id in running.session.journey.job_ids:
            status, _, body = running.post(
                "/jobs/confirm",
                body=urlencode(
                    {
                        "job_id": job_id,
                        "success_evidence": "the confirmed outcome is available",
                        "privacy_limits": "stay inside the approved root",
                        "approval_limits": "ask before external action",
                        "autonomy_limits": "do not change files",
                        "importance": "medium",
                        "cadence": "weekly",
                    }
                ),
            )
            if status != 200:
                raise AssertionError(f"confirmation failed: {status}")
            pages.append(body)
        status, _, body = running.post("/diagnose")
        if status != 200:
            raise AssertionError(f"diagnosis failed: {status}")
        pages.append(body)

    assert tree_digests(root) == before
    joined = "\n".join(pages)
    assert_no_canary_leak(joined, canaries, context="captured M3 pages")
    forbidden = ("https://", "<script", "<iframe", "<img", "fetch(", "websocket", "analytics")
    lowered = joined.lower()
    assert not [item for item in forbidden if item in lowered]
    return pages, canaries


def canary_derivations(canaries: list[str]) -> list[str]:
    return [derived for canary in canaries for derived in derivations_of(canary)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.artifact
    pcap = artifact.with_suffix(".pcap")
    # A fresh network namespace starts with every interface down.  Enable
    # only loopback; no host/external interface is imported into this child.
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    proxy = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Proxy)
    proxy.daemon_threads = True
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    os.environ.update(
        HTTP_PROXY=f"http://127.0.0.1:{proxy.server_address[1]}",
        HTTPS_PROXY=f"http://127.0.0.1:{proxy.server_address[1]}",
        ALL_PROXY=f"http://127.0.0.1:{proxy.server_address[1]}",
        NO_PROXY="127.0.0.1,localhost",
    )
    tcpdump = shutil.which("tcpdump") or "tcpdump"
    capture = subprocess.Popen(
        [tcpdump, "-i", "lo", "-nn", "-U", "-w", str(pcap)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.25)
    try:
        pages, canaries = _run_journey()
        journey_error = ""
    except BaseException as exc:  # evidence records failure without leaking fixture bytes
        pages, canaries = [], []
        journey_error = type(exc).__name__
    finally:
        capture.send_signal(signal.SIGINT)
        try:
            _, capture_stderr = capture.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            capture.kill()
            _, capture_stderr = capture.communicate()
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=2)

    interfaces = [
        line.split(":", 2)[1].strip().split("@", 1)[0]
        for line in subprocess.check_output(["ip", "-o", "link", "show"], text=True).splitlines()
        if ":" in line
    ]
    packet_lines = _tcpdump_lines(pcap) if pcap.exists() else []
    dns_lines = _tcpdump_lines(pcap, "udp port 53") if pcap.exists() else []
    packet_bytes = pcap.read_bytes() if pcap.exists() else b""
    needles = canary_derivations(canaries)
    canary_leaks = [needle for needle in canaries if needle.encode() in packet_bytes]
    derivation_leaks = [
        needle
        for needle in needles
        if needle.encode() in packet_bytes and needle not in canary_leaks
    ]
    endpoints = _packet_endpoints(packet_lines)
    non_loopback = [
        f"{source}>{destination}"
        for source, destination in endpoints
        if source != "127.0.0.1" or destination != "127.0.0.1"
    ]
    evidence = {
        "interfaces": interfaces,
        "loopback_enabled": any(
            "LOOPBACK" in line.upper() and "UP" in line.upper()
            for line in subprocess.check_output(
                ["ip", "-o", "link", "show", "lo"], text=True
            ).splitlines()
        ),
        "journey_complete": not journey_error,
        "journey_error": journey_error,
        "pages_checked": len(pages),
        "packet_count": len(packet_lines),
        "non_loopback_packets": non_loopback,
        "dns_packets": dns_lines,
        "proxy_requests": _Proxy.requests,
        "canary_leaks": canary_leaks,
        "derivation_leaks": derivation_leaks,
        "tcpdump_stderr": capture_stderr[-200:],
    }
    artifact.write_text(json.dumps(evidence, sort_keys=True, indent=2))
    return 0 if not journey_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
