"""JSON command-line adapter for the deterministic diagnosis engine.

This module is a shallow door. It parses arguments, calls an injected engine,
and prints canonical JSON. It cannot issue or impersonate a scope-approval
receipt. Collection and ``ScopeSnapshot.capture`` are not its job.

``build_engine()`` is the injection point. Tests monkeypatch it with a fake.
Task 8 wires the real ``DeterministicDiagnosisEngine``.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from capability_exchange.diagnosis.run import DiagnosisRunView, DiagnosisStateError

__all__ = [
    "DeterministicDiagnosisEngine",
    "PrepareDiagnosisRequest",
    "bind_consent_surface",
    "build_engine",
    "diagnosis_main",
    "reset_consent_surface",
    "start_or_reuse_consent_surface",
]


class _DiagnosisResult(Protocol):
    def dump_for_storage(self) -> dict[str, object]: ...


class DeterministicDiagnosisEngine(Protocol):
    """The only engine surface the command line is allowed to call."""

    def prepare(self, request: PrepareDiagnosisRequest) -> DiagnosisRunView: ...

    def status(self, run_id: str) -> DiagnosisRunView: ...

    def advance(self, run_id: str) -> DiagnosisRunView: ...

    def submit(self, run_id: str, proposal: object) -> DiagnosisRunView: ...

    def result(self, run_id: str) -> _DiagnosisResult: ...


@dataclass(frozen=True)
class PrepareDiagnosisRequest:
    """Candidate folders recorded without reading them."""

    roots: tuple[Path, ...]


@dataclass
class _BoundConsentSurface:
    session: object
    server: object
    thread: threading.Thread | None = None
    owned: bool = False


_BOUND_SURFACE: _BoundConsentSurface | None = None

_DIAGNOSIS_COMMANDS = frozenset({"prepare", "status", "advance", "submit", "result"})

_HELP = """dex-lens diagnosis — a local, read-only look that waits for your approval.

JSON goes to stdout. Refusals and human guidance go to stderr.

    dex-lens diagnosis prepare --root <folder> [--additional-root <folder>]
    dex-lens diagnosis status --run <id> --json
    dex-lens diagnosis advance --run <id> --json
    dex-lens diagnosis submit --run <id> --proposal <json-file>
    dex-lens diagnosis result --run <id> --format json|markdown

prepare records candidate folders and returns a run ID plus the local
approval URL. It does not collect. Approval happens only in the existing
local consent surface. This command cannot sign, send, install, repair,
or modify the inspected system.
"""


def build_engine() -> DeterministicDiagnosisEngine:
    """Return the process engine. Tests monkeypatch this function."""

    from capability_exchange.diagnosis.defaults import build_default_engine

    return build_default_engine()


def bind_consent_surface(session: object, server: object) -> None:
    """Reuse an already-running local consent surface."""

    global _BOUND_SURFACE
    _BOUND_SURFACE = _BoundConsentSurface(session=session, server=server, owned=False)


def reset_consent_surface() -> None:
    """Detach a bound surface. Owned servers are shut down."""

    global _BOUND_SURFACE
    surface = _BOUND_SURFACE
    _BOUND_SURFACE = None
    if surface is None or not surface.owned:
        return
    terminate = getattr(surface.session, "terminate", None)
    if callable(terminate):
        terminate()
    shutdown = getattr(surface.server, "shutdown", None)
    if callable(shutdown):
        shutdown()
    close = getattr(surface.server, "server_close", None)
    if callable(close):
        close()
    if surface.thread is not None:
        surface.thread.join(timeout=5)


def start_or_reuse_consent_surface(
    *,
    run_id: str,
    roots: tuple[Path, ...],
    engine: DeterministicDiagnosisEngine,
) -> str | None:
    """Start or reuse the existing local consent surface. Never open a browser.

    Attaches the engine's consent authority and run ID so the authenticated
    ``/approve`` action can issue a receipt. Does not collect. A reused
    surface is not snapshotted again. A newly started doorway uses the
    existing session constructor; this function does not call
    ``ScopeSnapshot.capture`` itself.
    """

    global _BOUND_SURFACE
    authority = getattr(engine, "consent_authority", None)
    if _BOUND_SURFACE is None:
        from capability_exchange.concierge.server import session_for_roots, start_server

        session = session_for_roots(roots)
        server = start_server(session)
        thread = threading.Thread(
            target=server.serve_forever,
            name="dex-lens-diagnosis-consent",
            daemon=True,
        )
        thread.start()
        _BOUND_SURFACE = _BoundConsentSurface(
            session=session,
            server=server,
            thread=thread,
            owned=True,
        )
    session = _BOUND_SURFACE.session
    if authority is not None:
        session.diagnosis_consent = authority
        session.diagnosis_run_id = run_id
    store = getattr(engine, "run_store", None)
    if store is not None:
        session.diagnosis_run_store = store
    port = getattr(_BOUND_SURFACE.server, "server_port", None)
    if port is None:
        return None
    url = f"http://127.0.0.1:{port}/"
    token = getattr(session, "bootstrap_token", "")
    if token:
        print(
            "Approve the exact scope in the local consent surface:\n"
            f"{url}?token={token}",
            file=sys.stderr,
        )
    return url


def diagnosis_main(argv: list[str] | None = None) -> int:
    """Dispatch one diagnosis command. A bare unknown word fails closed."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"--help", "-h", "help"}:
        print(_HELP, end="")
        return 0
    command = arguments[0]
    if command not in _DIAGNOSIS_COMMANDS:
        print(
            f"dex-lens: {command!r} is not a dex-lens diagnosis command.",
            file=sys.stderr,
        )
        print("Commands: " + ", ".join(sorted(_DIAGNOSIS_COMMANDS)), file=sys.stderr)
        return 2
    handlers: dict[str, Callable[[list[str]], int]] = {
        "prepare": _prepare,
        "status": _status,
        "advance": _advance,
        "submit": _submit,
        "result": _result,
    }
    try:
        return handlers[command](arguments[1:])
    except DiagnosisStateError as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        code = 0 if exc.code in {None, True} else (1 if exc.code is False else int(exc.code))
        return code


def _parser(prog: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=prog, description=description)


def _write_canonical_json(payload: object) -> None:
    sys.stdout.write(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _existing_roots(paths: Sequence[Path]) -> tuple[Path, ...] | None:
    resolved = tuple(path.expanduser().resolve() for path in paths)
    missing = tuple(path for path in resolved if not path.is_dir())
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        print(
            f"dex-lens: each diagnosis root must be an existing directory: {rendered}",
            file=sys.stderr,
        )
        return None
    return resolved


def _prepare(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis prepare",
        "Record candidate folders and return the local approval action. Read nothing.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Primary folder offered for later read-only inspection.",
    )
    parser.add_argument(
        "--additional-root",
        type=Path,
        action="append",
        default=[],
        help="Another candidate folder. May be repeated. Nothing is read yet.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Keep the local consent surface running until this run is approved.",
    )
    args = parser.parse_args(argv)
    roots = _existing_roots((args.root, *args.additional_root))
    if roots is None:
        return 2
    engine = build_engine()
    view = engine.prepare(PrepareDiagnosisRequest(roots=roots))
    approval_url = start_or_reuse_consent_surface(
        run_id=view.run_id,
        roots=roots,
        engine=engine,
    )
    if approval_url and view.approval_url is None:
        view = view.model_copy(update={"approval_url": approval_url})
    _write_canonical_json(view.dump_for_storage())
    if args.wait:
        return _wait_for_approval(engine, view.run_id)
    return 0


def _wait_for_approval(engine: DeterministicDiagnosisEngine, run_id: str) -> int:
    """Stay alive so the local /approve action can persist a receipt."""

    import time

    print(
        "Waiting for local approval. This process must stay running until you approve.",
        file=sys.stderr,
    )
    try:
        while True:
            receipt = engine.consent_authority.receipt_for(run_id)
            if receipt is not None:
                return 0
            approval = getattr(engine.run_store, "load_scope_approval", None)
            if callable(approval) and approval(run_id) is not None:
                return 0
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130


def _status(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis status",
        "Report proved progress without advancing the run.",
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write the canonical run view as JSON on stdout.",
    )
    args = parser.parse_args(argv)
    view = build_engine().status(args.run)
    _write_canonical_json(view.dump_for_storage())
    return 0


def _advance(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis advance",
        "Perform the next lawful read-only diagnosis transition.",
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write the canonical run view as JSON on stdout.",
    )
    args = parser.parse_args(argv)
    view = build_engine().advance(args.run)
    _write_canonical_json(view.dump_for_storage())
    return 0


def _submit(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis submit",
        "Offer a typed specialist proposal. The engine still owns the facts.",
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--proposal",
        type=Path,
        required=True,
        help="JSON file holding one specialist proposal.",
    )
    args = parser.parse_args(argv)
    proposal = _load_proposal(args.proposal)
    if proposal is None:
        return 2
    view = build_engine().submit(args.run, proposal)
    _write_canonical_json(view.dump_for_storage())
    return 0


def _result(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis result",
        "Print the closed canonical result. JSON bytes match the engine dump.",
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--format",
        required=True,
        choices=("json", "markdown"),
        help="json is the engine dump; markdown is only the canonical report.",
    )
    args = parser.parse_args(argv)
    result = build_engine().result(args.run)
    if args.format == "json":
        _write_canonical_json(result.dump_for_storage())
        return 0
    render = getattr(result, "render_markdown", None)
    if not callable(render):
        print("dex-lens: this result has no canonical markdown.", file=sys.stderr)
        return 2
    sys.stdout.write(str(render()))
    return 0


def _load_proposal(path: Path) -> object | None:
    if not path.is_file():
        print(f"dex-lens: no such proposal file: {path}", file=sys.stderr)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("dex-lens: the proposal must be JSON.", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"dex-lens: could not read the proposal: {exc}", file=sys.stderr)
        return None
