"""Produce sanitized packet/DNS/proxy evidence inside an isolated network."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import shutil
import signal
import socketserver
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, quote_plus, urlencode

from tests.adapters.claude_code.fixture_helpers import tree_digests
from tests.concierge.test_local_server import RunningServer
from tests.egress.harness import EGRESS_CANARIES, build_canary_system
from tests.fixtures.hostile.catalog import derivations_of

from capability_exchange.adapters.claude_code.containment import contained_inspection


class _Proxy(socketserver.BaseRequestHandler):
    requests: list[str] = []

    def handle(self) -> None:  # pragma: no cover - only runs on failed egress
        # An accepted-but-empty or stalled connection is still attempted
        # egress.  Record only a marker, never request bytes.
        self.requests.append("connection-accepted")
        self.request.settimeout(0.2)
        try:
            self.request.recv(4096)
        except (OSError, TimeoutError):
            return


def _tcpdump_lines(pcap: Path, expression: str | None = None) -> list[str]:
    command = [shutil.which("tcpdump") or "tcpdump", "-nn", "-r", str(pcap)]
    if expression:
        command.extend(shlex.split(expression))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("tcpdump could not read the capture")
    return [
        line
        for line in result.stdout.splitlines()
        if line and not line.startswith("reading from")
    ]


def _host(endpoint: str) -> str:
    value = endpoint.rstrip(" ,:")
    address, separator, port = value.rpartition(".")
    return address if separator and port.isdigit() else value


def _packet_endpoints(
    lines: list[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    endpoints: list[tuple[str, str]] = []
    unparsed: list[str] = []
    # Supports both IPv4 and IPv6; ``-i any`` may prefix interface/direction.
    pattern = re.compile(r"\b(IP6?)\s+([^ ]+)\s+>\s+([^ ]+)")
    for line in lines:
        match = pattern.search(line)
        if match is None:
            unparsed.append("unparsed-packet")
            continue
        endpoints.append((_host(match.group(2)), _host(match.group(3))))
    return endpoints, unparsed


def _forbidden_forms(canary: str) -> tuple[bytes, ...]:
    def encoded_forms(value: str) -> set[bytes]:
        raw = value.encode()
        return {
            raw,
            quote(value, safe="").encode(),
            quote_plus(value, safe="").encode(),
            base64.b64encode(raw),
            base64.urlsafe_b64encode(raw),
            json.dumps(value)[1:-1].encode(),
        }

    forms = encoded_forms(canary)
    forms.update(item.encode() for item in derivations_of(canary))
    for start in range(max(0, len(canary) - 11)):
        forms.update(encoded_forms(canary[start : start + 12]))
    return tuple(forms)


def _leak_markers(blob: bytes, canaries: list[str]) -> list[str]:
    """Return stable markers without putting a canary in the evidence file."""

    return [
        f"canary-{index}"
        for index, canary in enumerate(canaries, start=1)
        if any(form and form in blob for form in _forbidden_forms(canary))
    ]


def _run_journey() -> tuple[list[str], list[str], list[str]]:
    run_canary = f"m3-unique-canary-{uuid.uuid4().hex}"
    pages: list[str] = []
    with tempfile.TemporaryDirectory(prefix="dex-m3-fixture-") as base_dir:
        root = build_canary_system(Path(base_dir))
        (root / "CLAUDE.md").write_text(f"{run_canary}\n")
        canaries = [*EGRESS_CANARIES, run_canary]
        before = tree_digests(root)

        def collect(cancel_event: threading.Event):
            return contained_inspection(
                [str(root)], cancel_event=cancel_event
            ).envelope

        with RunningServer(collect, approved_root=root) as running:
            pages.append(running.bootstrap())
            status, _, body = running.post("/approve")
            if status != 200:
                raise RuntimeError("approval failed")
            pages.append(body)
            running.wait_for_collection()
            status, _, body = running.request("GET", "/session")
            if status != 200:
                raise RuntimeError("session failed")
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
                    raise RuntimeError("confirmation failed")
                pages.append(body)
            status, _, body = running.post("/diagnose")
            if status != 200:
                raise RuntimeError("diagnosis failed")
            pages.append(body)

        if tree_digests(root) != before:
            raise RuntimeError("inspected root changed during the journey")

    joined = "\n".join(pages)
    application_leaks = _leak_markers(joined.encode(), canaries)
    forbidden = ("https://", "<script", "<iframe", "<img", "fetch(", "websocket", "analytics")
    if any(item in joined.lower() for item in forbidden):
        raise RuntimeError("forbidden browser transport primitive rendered")
    return pages, canaries, application_leaks


def _capture_ready(process: subprocess.Popen[str]) -> bool:
    """Require tcpdump to remain alive through a bounded startup window."""

    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        time.sleep(0.05)
    return process.poll() is None


def _start_capture(pcap: Path) -> tuple[subprocess.Popen[str], BinaryIO]:
    """Open the pcap as root before tcpdump drops its filesystem privileges."""

    stream = pcap.open("wb")
    tcpdump = shutil.which("tcpdump") or "tcpdump"
    try:
        process = subprocess.Popen(
            [tcpdump, "-i", "any", "-nn", "-U", "-s", "0", "-w", "-"],
            stdout=stream,
            stderr=subprocess.PIPE,
            text=True,
        )
    except BaseException:
        stream.close()
        raise
    return process, stream


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.artifact
    pcap = artifact.with_suffix(".pcap")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    _Proxy.requests = []
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
    capture, capture_stream = _start_capture(pcap)
    capture_ready = _capture_ready(capture)
    pages: list[str] = []
    canaries: list[str] = []
    application_leaks: list[str] = []
    journey_error = ""
    if capture_ready:
        try:
            pages, canaries, application_leaks = _run_journey()
        except BaseException as exc:  # emit only the failure class
            journey_error = type(exc).__name__
    else:
        journey_error = "CaptureUnavailable"

    capture_timed_out = False
    if capture.poll() is None:
        capture.send_signal(signal.SIGINT)
    try:
        _, capture_stderr = capture.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        capture_timed_out = True
        capture.kill()
        _, capture_stderr = capture.communicate()
    capture_stream.close()
    capture_clean_exit = capture.returncode == 0 and not capture_timed_out
    proxy.shutdown()
    proxy.server_close()
    proxy_thread.join(timeout=2)

    interfaces = [
        line.split(":", 2)[1].strip().split("@", 1)[0]
        for line in subprocess.check_output(
            ["ip", "-o", "link", "show"], text=True
        ).splitlines()
        if ":" in line
    ]
    packet_lines = _tcpdump_lines(pcap) if pcap.is_file() else []
    dns_lines = (
        _tcpdump_lines(pcap, "(udp or tcp) and port 53")
        if pcap.is_file()
        else []
    )
    packet_bytes = pcap.read_bytes() if pcap.is_file() else b""
    endpoints, unparsed = _packet_endpoints(packet_lines)
    loopbacks = {"127.0.0.1", "::1"}
    non_loopback = [
        "non-loopback-packet"
        for source, destination in endpoints
        if source not in loopbacks or destination not in loopbacks
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
        "unparsed_packets": unparsed,
        "dns_packets": ["dns-packet"] * len(dns_lines),
        "proxy_requests": _Proxy.requests,
        "application_canary_leaks": application_leaks,
        "pcap_canary_leaks": _leak_markers(packet_bytes, canaries),
        "capture_ready": capture_ready,
        "capture_clean_exit": capture_clean_exit,
        "capture_timed_out": capture_timed_out,
        "capture_reported_error": "error" in capture_stderr.lower(),
    }
    artifact.write_text(json.dumps(evidence, sort_keys=True, indent=2))
    return 0 if not journey_error and capture_clean_exit else 1


if __name__ == "__main__":
    raise SystemExit(main())
