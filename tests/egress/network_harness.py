"""OS-backed M3 egress evidence harness.

The normal pytest suite exercises the concierge in-process.  This module adds
the missing wire-level proof: a child is launched in a fresh Linux network
namespace (or a Docker ``--network none`` equivalent) with only loopback
enabled, while ``tcpdump`` records the complete journey.  The formal gate runs
this module in a disposable, capability-minimized container; a developer run
has an explicit, visible capability result rather than
pretending that a monkeypatch is packet capture.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tests.fixtures.hostile.catalog import derivations_of


@dataclass(frozen=True, slots=True)
class NamespaceCapability:
    available: bool
    reason: str
    unshare: str | None = None
    ip: str | None = None
    tcpdump: str | None = None
    raw_socket: bool = False


@dataclass(frozen=True, slots=True)
class NamespaceRun:
    returncode: int
    stdout: str
    stderr: str
    evidence: dict[str, Any] | None


def _raw_capture_available() -> bool:
    try:
        probe = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
    except (AttributeError, OSError):
        return False
    probe.close()
    return True


def capability_probe() -> NamespaceCapability:
    """Check every privilege/tool the formal gate actually relies on."""

    if sys.flags.optimize:
        return NamespaceCapability(
            False,
            "Python optimization is enabled; safety assertions would be removable",
        )
    if sys.platform != "linux":
        return NamespaceCapability(
            False,
            f"Linux network namespaces required, got {sys.platform!r}",
        )
    isolated_container = os.environ.get("M3_EGRESS_NETWORK_ISOLATED") == "1"
    unshare = shutil.which("unshare")
    ip = shutil.which("ip")
    tcpdump = shutil.which("tcpdump")
    required_tools = (("ip", ip), ("tcpdump", tcpdump))
    if not isolated_container:
        required_tools = (("unshare", unshare), *required_tools)
    missing = [name for name, path in required_tools if path is None]
    if missing:
        return NamespaceCapability(
            False,
            f"missing required tools: {', '.join(missing)}",
            unshare,
            ip,
            tcpdump,
        )
    raw_socket = _raw_capture_available()
    if not raw_socket:
        return NamespaceCapability(
            False,
            "CAP_NET_RAW is unavailable (tcpdump/AF_PACKET cannot capture packets); "
            "run the formal gate in the isolated Linux runner harness",
            unshare,
            ip,
            tcpdump,
            False,
        )
    if not isolated_container:
        check = subprocess.run(
            [unshare, "--net", "--", "true"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if check.returncode != 0:
            detail = (check.stderr or check.stdout).strip().replace("\n", " ")
            return NamespaceCapability(
                False,
                f"unshare --net is unavailable: {detail or 'operation failed'}; "
                "run the formal gate in the isolated Linux runner harness",
                unshare,
                ip,
                tcpdump,
                True,
            )
    return NamespaceCapability(
        True,
        (
            "Linux network-disabled container and packet capture capabilities are available"
            if isolated_container
            else "Linux network namespace and packet capture capabilities are available"
        ),
        unshare,
        ip,
        tcpdump,
        True,
    )


def run_namespace_journey(artifact: Path, *, timeout: float = 120.0) -> NamespaceRun:
    """Run the child evidence producer in an isolated namespace."""

    capability = capability_probe()
    if not capability.available:
        raise RuntimeError(capability.reason)
    python = sys.executable
    command = [python, "-m", "tests.egress.namespace_probe", "--artifact", str(artifact)]
    if not os.environ.get("M3_EGRESS_NETWORK_ISOLATED") == "1":
        if capability.unshare is None:
            raise RuntimeError("unshare disappeared after the capability probe")
        command = [
            capability.unshare,
            "--net",
            "--mount-proc",
            "--fork",
            *command,
        ]
    env = os.environ.copy()
    repo = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (repo, str(Path(repo) / "src"), env.get("PYTHONPATH", "")))
    )
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    evidence = None
    if artifact.is_file():
        try:
            evidence = json.loads(artifact.read_text())
        except (OSError, json.JSONDecodeError):
            evidence = None
    return NamespaceRun(completed.returncode, completed.stdout, completed.stderr, evidence)


def assert_evidence(evidence: dict[str, Any]) -> None:
    """Validate the machine-readable namespace/pcap/DNS/proxy proof."""

    requirements = {
        "only loopback is present": evidence.get("interfaces") == ["lo"],
        "loopback is enabled": evidence.get("loopback_enabled") is True,
        "journey completed": evidence.get("journey_complete") is True,
        "adaptation completed and was undone": evidence.get("adaptation_complete") is True,
        "at least five pages were checked": evidence.get("pages_checked", 0) >= 5,
        "proxy accepted no request": evidence.get("proxy_requests") == [],
        "no DNS packet was captured": evidence.get("dns_packets") == [],
        "no non-loopback packet was captured": evidence.get("non_loopback_packets") == [],
        "every captured packet was parsed": evidence.get("unparsed_packets") == [],
        "application payload has no canary": evidence.get("application_canary_leaks") == [],
        "pcap has no contiguous canary": evidence.get("pcap_canary_leaks") == [],
        "capture became ready": evidence.get("capture_ready") is True,
        "capture exited cleanly": evidence.get("capture_clean_exit") is True,
        "capture did not time out": evidence.get("capture_timed_out") is False,
        "capture reported no error": evidence.get("capture_reported_error") is False,
        "at least one packet was captured": evidence.get("packet_count", 0) > 0,
    }
    failed = [name for name, passed in requirements.items() if not passed]
    if failed:
        raise RuntimeError(f"egress evidence failed: {', '.join(failed)}")


def canary_needles(canaries: list[str]) -> list[str]:
    """Return all raw and hash forms the pcap must not contain."""

    needles: list[str] = []
    for canary in canaries:
        needles.extend(derivations_of(canary))
    return needles


def temporary_artifact() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    directory = tempfile.TemporaryDirectory(prefix="dex-m3-egress-")
    return directory, Path(directory.name) / "evidence.json"


def capability_json(capability: NamespaceCapability) -> str:
    return json.dumps(asdict(capability), sort_keys=True)
