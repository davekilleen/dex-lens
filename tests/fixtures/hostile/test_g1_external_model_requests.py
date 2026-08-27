"""G1 hostile fixture 6 (gates.md item f): external model requests.

G1: any request to an external model requires a separate, explicit consent
distinct from inspection consent. The M1 build has **no model client at
all** — so the strongest possible assertion holds: no call path exists.
These tests prove it structurally (no model-client import anywhere in the
package, and only the M3 consented catalogue fetcher may import a network
client for the pinned public Dex catalogue GET; the contained child gets no
network configuration) and behaviorally (a fixture demanding model calls
changes nothing).
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.fixtures.hostile.catalog import (
    MODEL_REQUEST_TEXT,
    build_benign_system,
    build_model_request_system,
)
from tests.fixtures.hostile.pipeline import (
    FIXED_CONSENT_MOMENT,
    collect_from,
    normalized_bytes,
    serialized,
)

import capability_exchange
from capability_exchange.adapters.claude_code.containment import _child_environment

#: Modules that would constitute a model client or a general egress path. None
#: may be imported anywhere in the capability_exchange package except for the
#: explicit, consent-bounded allowances below.
FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "aiohttp",
        "anthropic",
        "boto3",
        "botocore",
        "cohere",
        "google.generativeai",
        "grpc",
        "http.client",
        "httpx",
        "llama_cpp",
        "mistralai",
        "ollama",
        "openai",
        "requests",
        "urllib.request",
        "urllib3",
        "websocket",
        "websockets",
        "xmlrpc.client",
    }
)

#: ``socket`` may appear in exactly one module: the containment child,
#: which uses it solely to PROVE the network is denied before any read.
SOCKET_ALLOWED_IN = "capability_exchange/adapters/claude_code/contained.py"

#: The complete set of reviewed egress paths. Each entry is a deliberate,
#: named decision:
#: - catalogue/fetch.py — the M3 consented GET of the public signed
#:   catalogue, identical for everyone, verified on-machine before shown.
#: The old receiptless Markdown POST in share/cli.py is closed; that module
#: now prints only a GitHub link and therefore has no network client import.
#: - contribution/hosted_intake.py — the optional stage-nine POST after the
#:   person reviews and approves one exact DisclosureManifest; identity is
#:   loaded lazily at that boundary and the adapter sends the approved bytes
#:   as its sole body (tests/egress/test_hosted_contribution_intake.py).
EGRESS_IMPORT_ALLOWED_IN: dict[str, tuple[str, ...]] = {
    "urllib.request": (
        "capability_exchange/catalogue/fetch.py",
        "capability_exchange/contribution/hosted_intake.py",
    ),
}


def _package_sources() -> list[Path]:
    package_root = Path(capability_exchange.__file__).resolve().parent
    return sorted(package_root.rglob("*.py"))


def _imports_of(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_g1_no_model_client_or_egress_import_exists_in_the_package() -> None:
    for source_path in _package_sources():
        imports = _imports_of(source_path)
        for name in imports:
            hits = [
                bad
                for bad in FORBIDDEN_IMPORTS
                if name == bad or name.startswith(bad + ".")
            ]
            hits = [
                bad
                for bad in hits
                if not str(source_path).endswith(EGRESS_IMPORT_ALLOWED_IN.get(bad, ("\0",)))
            ]
            assert not hits, (
                f"{source_path} imports {hits}: the build must contain no "
                f"model client and no unreviewed egress path (G1 item f)"
            )


def test_g1_socket_import_confined_to_the_containment_prover() -> None:
    for source_path in _package_sources():
        if "socket" in _imports_of(source_path):
            assert str(source_path).endswith(SOCKET_ALLOWED_IN), (
                f"{source_path} imports socket; only the containment child "
                f"may, and only to prove network denial"
            )


def test_g1_contained_child_environment_carries_no_network_configuration() -> None:
    environment = _child_environment()
    assert set(environment) <= {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PATH", "HOME"}
    for key in environment:
        assert "PROXY" not in key.upper()
        assert "API" not in key.upper()


def test_g1_model_request_fixture_changes_nothing(tmp_path: Path) -> None:
    requesting_root = build_model_request_system(tmp_path / "requesting")
    control_root = build_benign_system(tmp_path / "control")
    # Same probes, same behavior: the request text is data, not a directive.
    requesting = collect_from(requesting_root, taken_at=FIXED_CONSENT_MOMENT)
    control = collect_from(control_root, taken_at=FIXED_CONSENT_MOMENT)
    assert [p.probe_id for p in requesting.probes] == [p.probe_id for p in control.probes]
    assert [p.health for p in requesting.probes] == [p.health for p in control.probes]


def test_g1_model_request_text_never_in_envelope(tmp_path: Path) -> None:
    root = build_model_request_system(tmp_path)
    payload = serialized(collect_from(root))
    assert "external model" not in payload
    assert "completions API" not in payload
    assert "api.model.invalid" not in payload


def test_g1_model_request_fixture_normalized_output_is_control_shaped(
    tmp_path: Path,
) -> None:
    # Byte-level variant of behavior invariance for the model-request
    # fixture: identical trees except the requesting text.
    requesting_root = build_benign_system(tmp_path / "requesting")
    control_root = build_benign_system(tmp_path / "control")
    (requesting_root / "CLAUDE.md").write_text("Instructions.\n" + MODEL_REQUEST_TEXT)
    (control_root / "CLAUDE.md").write_text("Instructions.\n")
    requesting = collect_from(requesting_root, taken_at=FIXED_CONSENT_MOMENT)
    control = collect_from(control_root, taken_at=FIXED_CONSENT_MOMENT)
    assert normalized_bytes(requesting) == normalized_bytes(control)
