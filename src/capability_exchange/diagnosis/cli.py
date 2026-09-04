"""JSON command-line adapter for the deterministic diagnosis engine.

This module is a shallow door. It parses arguments, calls an injected engine,
and prints canonical JSON. Collection is not its job. Scope approval in the
skill path is an explicit ``diagnosis approve`` after the person says yes
in the same chat. The optional local page is not required.

``build_engine()`` is the injection point. Tests monkeypatch it with a fake.
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

from pydantic import ValidationError

from capability_exchange.boundary.crashlog import write_crash_log
from capability_exchange.diagnosis.payload_guard import (
    REMOVE_ABSOLUTE_PATH,
    REMOVE_SECRET,
    HostilePayloadError,
    parse_specialist_proposal,
    refuse_hostile_payload,
)
from capability_exchange.diagnosis.run import (
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.specialists import SpecialistProposalError
from capability_exchange.diagnosis.work import AnalysisMode, WorkQueueError

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

    def work(self, run_id: str) -> object: ...

    def pending_work(self, run_id: str) -> tuple[object, ...]: ...

    def work_context(self, run_id: str) -> tuple[object, ...]: ...

    def submit_work(
        self,
        run_id: str,
        packet_id: str,
        proposals: tuple[object, ...] = (),
    ) -> DiagnosisRunView: ...

    def submit(self, run_id: str, proposal: object) -> DiagnosisRunView: ...

    def result(self, run_id: str) -> _DiagnosisResult: ...


@dataclass(frozen=True)
class PrepareDiagnosisRequest:
    """Candidate folders recorded without reading them."""

    roots: tuple[Path, ...]
    analysis_mode: AnalysisMode = AnalysisMode.GUIDED


@dataclass
class _BoundConsentSurface:
    session: object
    server: object
    thread: threading.Thread | None = None
    owned: bool = False


_BOUND_SURFACE: _BoundConsentSurface | None = None

_DIAGNOSIS_COMMANDS = frozenset(
    {"prepare", "approve", "status", "advance", "work", "submit", "result"}
)

_HELP = """dex-lens diagnosis — a local, read-only look that waits for your approval.

JSON goes to stdout. Refusals and human guidance go to stderr.

    dex-lens diagnosis prepare --root <folder> [--mode guided-analysis|inventory-only]
    dex-lens diagnosis approve --run <id>
    dex-lens diagnosis status --run <id> --json
    dex-lens diagnosis advance --run <id> --json
    dex-lens diagnosis work --run <id> --json
    dex-lens diagnosis submit --run <id> --packet <id> [--proposal <json-file>]
    dex-lens diagnosis result --run <id> --format json|markdown

prepare records candidate folders and returns a run ID. It does not collect.
Approval happens in the same chat: show the person the exact folders, wait
for a clear yes, then run approve. This command cannot sign, send, install,
repair, or modify the inspected system.
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
            flush=True,
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
        "approve": _approve,
        "status": _status,
        "advance": _advance,
        "work": _work,
        "submit": _submit,
        "result": _result,
    }
    try:
        return handlers[command](arguments[1:])
    except DiagnosisStateError as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2
    except (WorkQueueError, SpecialistProposalError) as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2
    except ValidationError:
        # Never render a pydantic error here: it repeats the offending input
        # value, which on this path is specialist or vault text.
        print(
            "dex-lens: the payload is not a closed typed diagnosis value.",
            file=sys.stderr,
        )
        return 2
    except SystemExit as exc:
        code = 0 if exc.code in {None, True} else (1 if exc.code is False else int(exc.code))
        return code
    except Exception as exc:  # crash boundary — KeyboardInterrupt passes through
        # First caller of boundary/crashlog.py in src/: the record keeps
        # structure only. The message is never printed or stored, because a
        # message is interpolated from runtime values and can carry vault
        # content — that is the whole point of the module.
        _record_crash(exc)
        print(_CRASH_SENTENCE, file=sys.stderr)
        return 70


#: Fixed by design: no exception text, no path, ever. A crash on this surface
#: must not become a second way for inspected-system content to reach a screen.
_CRASH_SENTENCE = (
    "dex-lens: this command stopped on an unexpected error; "
    "only a redacted crash log is kept locally."
)


def _record_crash(exc: Exception) -> None:
    """Write the redacted crash record; a failed write forfeits only the log."""

    try:
        from capability_exchange.catalogue.subscription import default_lens_app_storage

        write_crash_log(exc, default_lens_app_storage() / "crash-logs")
    except Exception:  # the crash boundary never propagates
        pass


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


def _write_guarded_canonical_json(payload: object) -> int:
    """Screen an outbound diagnosis payload exactly as the MCP adapter does.

    ``mcp_server._dump``/``_dump_work`` and the work tool refuse these payloads
    on the MCP wire; the CLI prints the same payloads, so it must refuse the
    same ones. The refusal never echoes the offending value. The consent
    surface prints are deliberately not routed through here: approved roots
    and the local token are the person's own screen before any reading.
    """

    try:
        refuse_hostile_payload(payload)
    except HostilePayloadError as exc:
        print(_HOSTILE_GUIDANCE[exc.required_step], file=sys.stderr)
        return 2
    _write_canonical_json(payload)
    return 0


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


def _print_offered_folders(run_id: str, roots: tuple[Path, ...], *, approved: bool) -> None:
    heading = (
        "Approved. This diagnosis will look only at:"
        if approved
        else "This diagnosis will look only at:"
    )
    lines = [heading, *(f"  {root}" for root in roots)]
    if not approved:
        lines.extend(
            (
                "Nothing has been read. If that is the folder, say yes in this chat.",
                f"Then run: dex-lens diagnosis approve --run {run_id}",
            )
        )
    print("\n".join(lines), file=sys.stderr, flush=True)


def _prepare(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis prepare",
        "Record candidate folders and return the chat approval action. Read nothing.",
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
        "--mode",
        choices=(AnalysisMode.GUIDED.value, AnalysisMode.INVENTORY_ONLY.value),
        default=AnalysisMode.GUIDED.value,
        help="Analysis mode. Guided analysis issues engine-owned specialist work.",
    )
    parser.add_argument(
        "--consent-surface",
        action="store_true",
        help="Also start the optional local approval page. Not required in chat.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Keep the optional local page running until this run is approved.",
    )
    args = parser.parse_args(argv)
    if args.wait and not args.consent_surface:
        print(
            "dex-lens: --wait is only for the optional local page. "
            "In chat, run dex-lens diagnosis approve after they say yes.",
            file=sys.stderr,
            flush=True,
        )
        return 2
    roots = _existing_roots((args.root, *args.additional_root))
    if roots is None:
        return 2
    engine = build_engine()
    view = engine.prepare(
        PrepareDiagnosisRequest(
            roots=roots,
            analysis_mode=AnalysisMode(args.mode),
        )
    )
    if args.consent_surface:
        approval_url = start_or_reuse_consent_surface(
            run_id=view.run_id,
            roots=roots,
            engine=engine,
        )
        if approval_url and view.approval_url is None:
            view = view.model_copy(update={"approval_url": approval_url})
    _print_offered_folders(view.run_id, roots, approved=False)
    _write_canonical_json(view.dump_for_storage())
    if args.wait:
        return _wait_for_approval(engine, view.run_id)
    return 0


def _approve(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis approve",
        "Record the person's yes for the exact folders this run offered.",
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        default=[],
        help="Folder being approved. Repeat for each offered folder. Defaults to the prepared set.",
    )
    parser.add_argument(
        "--additional-root",
        type=Path,
        action="append",
        default=[],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    engine = build_engine()
    store = getattr(engine, "run_store", None)
    authority = getattr(engine, "consent_authority", None)
    if store is None or authority is None:
        print(
            "dex-lens: this engine cannot record a chat scope approval.",
            file=sys.stderr,
            flush=True,
        )
        return 2
    engine.status(args.run)
    offered = store.load_candidate_scope(args.run)
    if offered is None:
        print(
            "dex-lens: unknown diagnosis run cannot be approved.",
            file=sys.stderr,
            flush=True,
        )
        return 2
    requested = tuple(args.root) + tuple(args.additional_root)
    if requested:
        roots = _existing_roots(requested)
        if roots is None:
            return 2
    else:
        roots = _existing_roots(tuple(Path(root) for root in offered.candidate_roots))
        if roots is None:
            return 2
    from capability_exchange.concierge.consent import persist_offered_scope_approval

    persist_offered_scope_approval(
        authority,
        store,
        run_id=args.run,
        roots=roots,
    )
    view = engine.status(args.run)
    if view.stage is DiagnosisStage.CREATED:
        view = engine.advance(args.run)
    _print_offered_folders(args.run, roots, approved=True)
    _write_canonical_json(view.dump_for_storage())
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


def _work(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis work",
        "Return the next engine-issued specialist packet, or a typed empty result.",
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write the canonical work payload as JSON on stdout.",
    )
    args = parser.parse_args(argv)
    engine = build_engine()
    packets = engine.pending_work(args.run)
    if not packets:
        payload: dict[str, object] = {"packet": None, "packets": []}
    else:
        # ``packets`` is the whole legal round, so a host fans every packet
        # out to parallel workers from this one fetch; ``packet`` stays the
        # first pending entry for compatibility. The legend rides alongside
        # the round exactly once so a host can cite the opaque
        # evidence/observation tokens without reading engine source. It
        # never joins any packet's digest-bound identity.
        dumped = [_json_packet(item) for item in packets]
        payload = {
            "packet": dumped[0],
            "packets": dumped,
            "evidence_legend": [
                _json_row(row) for row in engine.work_context(args.run)
            ],
        }
    return _write_guarded_canonical_json(payload)


def _json_packet(packet: object) -> object:
    """Dump one typed work packet; already-plain packets pass through."""

    dump = getattr(packet, "model_dump", None)
    return dump(mode="json") if callable(dump) else packet


def _json_row(row: object) -> object:
    """Dump one typed legend row; already-plain rows pass through."""

    dump = getattr(row, "model_dump", None)
    return dump(mode="json") if callable(dump) else row


def _submit(argv: list[str]) -> int:
    parser = _parser(
        "dex-lens diagnosis submit",
        "Offer typed specialist responses for one engine-issued packet.",
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--packet",
        help="Engine-issued packet ID. When omitted, submit one legacy proposal.",
    )
    parser.add_argument(
        "--proposal",
        type=Path,
        action="append",
        default=[],
        help="JSON file holding one specialist proposal. May be repeated.",
    )
    args = parser.parse_args(argv)
    engine = build_engine()
    if args.packet:
        proposals: list[object] = []
        for path in args.proposal:
            proposal = _load_proposal(path)
            if proposal is None:
                return 2
            typed = _typed_proposal(proposal)
            if typed is None:
                return 2
            proposals.append(typed)
        view = engine.submit_work(args.run, args.packet, tuple(proposals))
    else:
        if len(args.proposal) != 1:
            print(
                "dex-lens: legacy submit requires exactly one --proposal file.",
                file=sys.stderr,
            )
            return 2
        proposal = _load_proposal(args.proposal[0])
        if proposal is None:
            return 2
        view = engine.submit(args.run, proposal)
    return _write_guarded_canonical_json(view.dump_for_storage())


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
        return _write_guarded_canonical_json(result.dump_for_storage())
    render = getattr(result, "render_markdown", None)
    if not callable(render):
        print("dex-lens: this result has no canonical markdown.", file=sys.stderr)
        return 2
    # WO-022, decided 2026-09-03: the footer now renders its location
    # home-relative, so the rendered report carries no account name and the
    # markdown surface is guarded like every other outbound surface.
    rendered = str(render())
    try:
        refuse_hostile_payload(rendered)
    except HostilePayloadError as exc:
        print(_HOSTILE_GUIDANCE[exc.required_step], file=sys.stderr)
        return 2
    sys.stdout.write(rendered)
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


_HOSTILE_GUIDANCE = {
    REMOVE_SECRET: "dex-lens: secret material is not retained on the diagnosis wire.",
    REMOVE_ABSOLUTE_PATH: "dex-lens: absolute paths are not retained on the diagnosis wire.",
}


def _typed_proposal(payload: object) -> object | None:
    """Validate one proposal here, so a bad file never costs a packet attempt.

    The engine records a durable attempt for anything it rejects. MCP parses
    ahead of the engine for that reason and the CLI must match it, or the same
    bytes would consume a retry on one adapter and none on the other. Refusals
    never repeat the offending value.
    """

    try:
        typed = parse_specialist_proposal(payload)
    except ValueError as exc:
        # ``parse_specialist_proposal`` raises plain ValueError carrying only
        # fixed rule text plus failing field names — never pydantic messages
        # or submitted values — so exactly that wording is printed verbatim.
        # Any other ValueError subclass keeps the closed sentence: its text
        # could interpolate submitted values.
        message = (
            str(exc)
            if type(exc) is ValueError
            else "specialist proposal is not a closed typed payload"
        )
        print(f"dex-lens: {message}", file=sys.stderr)
        return None
    try:
        refuse_hostile_payload(typed.model_dump())
    except HostilePayloadError as exc:
        print(_HOSTILE_GUIDANCE[exc.required_step], file=sys.stderr)
        return None
    return typed
