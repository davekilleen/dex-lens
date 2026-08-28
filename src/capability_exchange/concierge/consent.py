"""Short-lived local consent authority for diagnosis scope receipts."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.concierge.collection import ScopeSnapshot
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    NEXT_ACTION,
    ApprovedScopeReceipt,
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
    canonical_json_digest,
)

__all__ = [
    "CHAT_APPROVAL_SESSION_ID",
    "InMemoryConsentStore",
    "LocalScopeConsentAuthority",
    "opaque_candidate_locator",
    "persist_offered_scope_approval",
]

CHAT_APPROVAL_SESSION_ID = "cli-chat"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def opaque_candidate_locator(root: Path) -> str:
    """Hash a candidate root without retaining the raw path."""

    resolved = Path(root).expanduser().resolve(strict=False)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    return f"candidate:sha256:{digest}"


@dataclass
class InMemoryConsentStore:
    """Process-memory consent store. Not the durable Task 6 run store."""

    pending: dict[str, tuple[str, ...]] = field(default_factory=dict)
    receipts: dict[str, ApprovedScopeReceipt] = field(default_factory=dict)


class LocalScopeConsentAuthority:
    """The only component allowed to issue an approved-scope receipt."""

    def __init__(
        self,
        storage: InMemoryConsentStore | None = None,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = storage if storage is not None else InMemoryConsentStore()
        self._now = now

    def prepare(self, candidate_roots: tuple[Path, ...]) -> DiagnosisRunView:
        """Record a run and opaque candidate locators. Read nothing."""

        if not candidate_roots:
            raise DiagnosisStateError("diagnosis prepare requires at least one candidate root")
        locators = tuple(opaque_candidate_locator(root) for root in candidate_roots)
        if len(set(locators)) != len(locators):
            raise DiagnosisStateError("candidate roots must be distinct")
        run_id = "run:" + secrets.token_hex(16)
        self._store.pending[run_id] = locators
        return DiagnosisRunView(
            run_id=run_id,
            stage=DiagnosisStage.CREATED,
            next_action=NEXT_ACTION[DiagnosisStage.CREATED],
            input_identity=None,
            approval_url=None,
        )

    def receipt_for(self, run_id: str) -> ApprovedScopeReceipt | None:
        """Read-only access for CLI and MCP adapters."""

        return self._store.receipts.get(run_id)

    def approve_from_local_session(
        self,
        *,
        run_id: str,
        scope_snapshot: ScopeSnapshot,
        authenticated_session_id: str,
    ) -> ApprovedScopeReceipt:
        """Issue a receipt only from the authenticated local consent session."""

        if not authenticated_session_id.strip():
            raise DiagnosisStateError("scope approval requires an authenticated local session")
        pending = self._store.pending.get(run_id)
        if pending is None:
            raise DiagnosisStateError("unknown diagnosis run cannot be approved")
        existing = self._store.receipts.get(run_id)
        if existing is not None:
            return existing
        references = tuple(
            descriptor.scope_reference for descriptor in scope_snapshot.source_descriptors
        )
        receipt = ApprovedScopeReceipt(
            run_id=run_id,
            scope_references=references,
            scope_digest=canonical_json_digest(list(references)),
            session_receipt_id=f"session:{authenticated_session_id[:32]}",
            approved_at=self._now(),
        )
        self._store.receipts[run_id] = receipt
        return receipt

    def approve_offered_scope(
        self,
        *,
        run_id: str,
        scope_snapshot: ScopeSnapshot,
        authenticated_session_id: str,
        offered_locators: tuple[str, ...],
    ) -> ApprovedScopeReceipt:
        """Issue a receipt for folders the person just approved in chat."""

        live = tuple(
            opaque_candidate_locator(descriptor.canonical_root)
            for descriptor in scope_snapshot.source_descriptors
        )
        if live != offered_locators:
            raise DiagnosisStateError("offered folders do not match this run")
        pending = self._store.pending.get(run_id)
        if pending is None:
            self._store.pending[run_id] = offered_locators
        elif pending != offered_locators:
            raise DiagnosisStateError("offered folders do not match this run")
        return self.approve_from_local_session(
            run_id=run_id,
            scope_snapshot=scope_snapshot,
            authenticated_session_id=authenticated_session_id,
        )

    def view_for(self, run_id: str) -> DiagnosisRunView:
        receipt = self.receipt_for(run_id)
        if receipt is None:
            if run_id not in self._store.pending:
                raise DiagnosisStateError("unknown diagnosis run")
            return DiagnosisRunView(
                run_id=run_id,
                stage=DiagnosisStage.CREATED,
                next_action=NEXT_ACTION[DiagnosisStage.CREATED],
                input_identity=None,
            )
        return DiagnosisRunView(
            run_id=run_id,
            stage=DiagnosisStage.SCOPE_APPROVED,
            next_action=NEXT_ACTION[DiagnosisStage.SCOPE_APPROVED],
            input_identity=canonical_json_digest(
                {"engine_version": ENGINE_VERSION, "scope_digest": receipt.scope_digest}
            ),
        )


def persist_offered_scope_approval(
    authority: LocalScopeConsentAuthority,
    run_store: object,
    *,
    run_id: str,
    roots: tuple[Path, ...],
    session_id: str = CHAT_APPROVAL_SESSION_ID,
) -> ApprovedScopeReceipt:
    """Record the same durable receipt the local /approve action would write."""

    from capability_exchange.concierge.collection import (
        ScopeSnapshot,
        default_source_descriptors,
    )

    offered = getattr(run_store, "load_candidate_scope", lambda _run_id: None)(run_id)
    if offered is None:
        raise DiagnosisStateError("unknown diagnosis run cannot be approved")
    locators = tuple(opaque_candidate_locator(root) for root in roots)
    if locators != offered.locators:
        raise DiagnosisStateError("offered folders do not match this run")
    descriptors = default_source_descriptors(roots) if len(roots) > 1 else None
    try:
        snapshot = ScopeSnapshot.capture(roots, source_descriptors=descriptors)
    except ValueError as exc:
        raise DiagnosisStateError("approved root identity changed; start a new run") from exc
    existing = getattr(run_store, "load_scope_approval", lambda _run_id: None)(run_id)
    if existing is not None:
        return existing.receipt
    receipt = authority.approve_offered_scope(
        run_id=run_id,
        scope_snapshot=snapshot,
        authenticated_session_id=session_id,
        offered_locators=offered.locators,
    )
    persist = getattr(run_store, "save_scope_approval", None)
    if not callable(persist):
        raise DiagnosisStateError("diagnosis run store cannot persist scope approval")
    persist(receipt, approved_roots=tuple(str(root) for root in roots))
    return receipt
