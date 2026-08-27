"""The real hosted intake preserves the one-body contribution contract."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request

import pytest

from capability_exchange.concierge.journey import ContributionHandle
from capability_exchange.contribution.consent import PermissionSet
from capability_exchange.contribution.hosted_intake import (
    HostedAuthorizationControl,
    HostedContributionIntake,
    HostedCorrectionControl,
    HostedIntakeError,
    HostedReceiptLedger,
    HostedSessionCredentials,
    HostedSubmissionControl,
)


def test_hosted_intake_imports_cleanly_in_a_fresh_process() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = "src"

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from capability_exchange.contribution.hosted_intake import HostedContributionIntake",
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


class _Response:
    def __init__(
        self,
        payload: dict[str, object],
        status: int = 200,
        *,
        final_url: str | None = None,
    ) -> None:
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")
        self._final_url = final_url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self._payload

    def geturl(self) -> str | None:
        return self._final_url


def _hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _permissions() -> PermissionSet:
    return PermissionSet(
        review=True,
        storage=True,
        moderation=True,
        attribution=False,
        reuse=True,
        distribution=True,
    )


def _handle(payload: bytes) -> ContributionHandle:
    return ContributionHandle(
        manifest_byte_hash=_hash(payload),
        revocation_token="revocation-v1:" + ("a" * 64),
        consent_hash=_hash(b"consent-record"),
        idempotency_key="submission-" + ("b" * 32),
        permissions=_permissions(),
    )


def test_hosted_control_and_receipt_state_cross_only_the_typed_g2_boundary() -> None:
    handle = _handle(b'{"method":"A bounded reusable method."}')
    control = HostedSubmissionControl.from_handle(handle)

    assert control.dump_for_transmission() == {
        "manifest_byte_hash": handle.manifest_byte_hash,
        "consent_hash": handle.consent_hash,
        "receipt_binding": handle.receipt_binding,
        "idempotency_key": handle.idempotency_key,
        "permission_review": True,
        "permission_storage": True,
        "permission_moderation": True,
        "permission_attribution": False,
        "permission_reuse": True,
        "permission_distribution": True,
    }
    assert HostedReceiptLedger.empty().dump_for_storage() == {
        "receipts": {},
        "schema_version": 1,
    }
    assert HostedAuthorizationControl(bearer_token="linked-token").dump_for_transmission() == {
        "bearer_token": "linked-token"
    }
    assert HostedCorrectionControl(
        replacement_receipt_id="ccr_prior"
    ).dump_for_transmission() == {"replacement_receipt_id": "ccr_prior"}


def test_submit_sends_exact_bytes_as_the_only_body_and_stores_bound_receipt(
    tmp_path: Path,
) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)
    seen: list[Request] = []

    def open_request(request: Request, *, timeout: float) -> _Response:
        assert timeout == 7.0
        seen.append(request)
        return _Response(
            {
                "receipt_id": "ccr_123",
                "manifest_byte_hash": handle.manifest_byte_hash,
                "handle_binding": handle.receipt_binding,
                "accepted": True,
                "status": "submitted-for-review",
            }
        )

    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=tmp_path / "receipts.json",
        base_url="https://api.heydex.ai",
        opener=open_request,
        timeout=7.0,
    )

    receipt = intake.submit(payload, handle=handle)

    assert receipt.accepted is True
    assert len(seen) == 1
    request = seen[0]
    assert request.full_url.endswith("/api/capability-contributions/submit")
    assert request.method == "POST"
    assert request.data == payload
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["authorization"] == "Bearer hosted-session-token"
    assert headers["x-dex-manifest-hash"] == handle.manifest_byte_hash
    assert headers["x-dex-consent-hash"] == handle.consent_hash
    assert headers["x-dex-receipt-binding"] == handle.receipt_binding
    assert headers["x-dex-idempotency-key"] == handle.idempotency_key
    assert headers["x-dex-permission-review"] == "true"
    assert headers["x-dex-permission-attribution"] == "false"
    assert handle.revocation_token not in json.dumps(headers)
    stored = json.loads((tmp_path / "receipts.json").read_text(encoding="utf-8"))
    assert stored["receipts"][handle.receipt_binding] == {
        "manifest_byte_hash": handle.manifest_byte_hash,
        "receipt_id": "ccr_123",
        "status": "submitted-for-review",
    }


def test_submit_refuses_bytes_that_do_not_match_the_approved_manifest_hash(
    tmp_path: Path,
) -> None:
    approved = b'{"method":"The approved method."}'
    handle = _handle(approved)
    calls: list[Request] = []
    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=tmp_path / "receipts.json",
        opener=lambda request, **_kwargs: calls.append(request),
    )

    with pytest.raises(HostedIntakeError, match="approved manifest hash"):
        intake.submit(b'{"method":"Different bytes."}', handle=handle)

    assert calls == []
    assert not (tmp_path / "receipts.json").exists()


def test_hosted_intake_refuses_the_raw_deployment_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pinned HTTPS host"):
        HostedContributionIntake(
            session_token=lambda: "hosted-session-token",
            receipt_store=tmp_path / "receipts.json",
            base_url="https://gallant-reindeer-229.eu-west-1.convex.site",
        )


@pytest.mark.parametrize(
    "base_url",
    (
        "https://api.heydex.ai:444",
        "https://api.heydex.ai/extra",
        "https://api.heydex.ai/?redirect=true",
    ),
)
def test_hosted_intake_refuses_any_noncanonical_authority_or_base_path(
    tmp_path: Path,
    base_url: str,
) -> None:
    with pytest.raises(ValueError, match="pinned HTTPS host"):
        HostedContributionIntake(
            session_token=lambda: "hosted-session-token",
            receipt_store=tmp_path / "receipts.json",
            base_url=base_url,
        )


def test_hosted_intake_refuses_a_redirected_receipt(tmp_path: Path) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)

    def redirected(_request: Request, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "receipt_id": "ccr_redirected",
                "manifest_byte_hash": handle.manifest_byte_hash,
                "handle_binding": handle.receipt_binding,
                "accepted": True,
                "status": "submitted-for-review",
            },
            final_url="https://attacker.example/receipt",
        )

    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=tmp_path / "receipts.json",
        opener=redirected,
    )

    with pytest.raises(HostedIntakeError, match="redirect"):
        intake.submit(payload, handle=handle)


def test_withdraw_uses_the_bound_receipt_and_sends_no_body(tmp_path: Path) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)
    calls: list[Request] = []

    def open_request(request: Request, *, timeout: float) -> _Response:
        del timeout
        calls.append(request)
        if request.full_url.endswith("/submit"):
            return _Response(
                {
                    "receipt_id": "ccr_456",
                    "manifest_byte_hash": handle.manifest_byte_hash,
                    "handle_binding": handle.receipt_binding,
                    "accepted": True,
                    "status": "submitted-for-review",
                }
            )
        return _Response(
            {
                "receipt_id": "ccr_456",
                "manifest_byte_hash": handle.manifest_byte_hash,
                "handle_binding": handle.receipt_binding,
                "withdrawn": True,
                "status": "withdrawn",
            }
        )

    store = tmp_path / "receipts.json"
    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=open_request,
    )
    intake.submit(payload, handle=handle)

    receipt = intake.withdraw(handle)

    assert receipt.withdrawn is True
    request = calls[-1]
    assert request.full_url.endswith("/api/capability-contributions/withdraw")
    assert request.method == "POST"
    assert request.data == b""
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["x-dex-receipt-id"] == "ccr_456"
    assert headers["x-dex-manifest-hash"] == handle.manifest_byte_hash
    assert headers["x-dex-receipt-binding"] == handle.receipt_binding
    assert not store.exists(), "verified withdrawal deletes the local receipt authority"


def test_pending_receipt_can_withdraw_by_binding_if_final_receipt_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)
    calls: list[Request] = []

    def open_request(request: Request, *, timeout: float) -> _Response:
        del timeout
        calls.append(request)
        if request.full_url.endswith("/submit"):
            return _Response(
                {
                    "receipt_id": "ccr_recover",
                    "manifest_byte_hash": handle.manifest_byte_hash,
                    "handle_binding": handle.receipt_binding,
                    "accepted": True,
                    "status": "submitted-for-review",
                }
            )
        return _Response(
            {
                "receipt_id": "ccr_recover",
                "manifest_byte_hash": handle.manifest_byte_hash,
                "handle_binding": handle.receipt_binding,
                "withdrawn": True,
                "status": "withdrawn",
            }
        )

    store = tmp_path / "receipts.json"
    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=open_request,
    )
    original_record = intake._record

    def fail_final_record(binding: str, receipt: object) -> None:
        if getattr(receipt, "status", None) == "submitted-for-review":
            raise OSError("simulated disk failure after remote acceptance")
        original_record(binding, receipt)  # type: ignore[arg-type]

    monkeypatch.setattr(intake, "_record", fail_final_record)
    with pytest.raises(OSError, match="simulated disk failure"):
        intake.submit(payload, handle=handle)

    pending = json.loads(store.read_text(encoding="utf-8"))
    assert pending["receipts"][handle.receipt_binding]["status"] == "submitting"
    recovered = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=open_request,
    )
    assert recovered.withdraw(handle).withdrawn is True
    headers = {name.lower(): value for name, value in calls[-1].header_items()}
    assert "x-dex-receipt-id" not in headers
    assert not store.exists()


def test_fresh_process_can_check_and_withdraw_a_saved_receipt(tmp_path: Path) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)
    store = tmp_path / "receipts.json"

    def submit_response(_request: Request, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "receipt_id": "ccr_saved",
                "manifest_byte_hash": handle.manifest_byte_hash,
                "handle_binding": handle.receipt_binding,
                "accepted": True,
                "status": "submitted-for-review",
            }
        )

    HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=submit_response,
    ).submit(payload, handle=handle)

    calls: list[Request] = []

    def recovery_response(request: Request, *, timeout: float) -> _Response:
        del timeout
        calls.append(request)
        if request.full_url.endswith("/status"):
            return _Response(
                {
                    "receipt_id": "ccr_saved",
                    "manifest_byte_hash": handle.manifest_byte_hash,
                    "status": "submitted-for-review",
                    "created_at": 1_000,
                    "updated_at": 1_000,
                }
            )
        return _Response(
            {
                "receipt_id": "ccr_saved",
                "manifest_byte_hash": handle.manifest_byte_hash,
                "handle_binding": handle.receipt_binding,
                "withdrawn": True,
                "status": "withdrawn",
            }
        )

    recovered = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=recovery_response,
    )

    status = recovered.status_saved("ccr_saved")
    assert status.status == "submitted-for-review"
    assert calls[-1].method == "GET"
    receipt = recovered.withdraw_saved("ccr_saved")
    assert receipt.withdrawn is True
    assert calls[-1].data == b""
    assert not store.exists()


def test_correction_uses_a_fresh_approved_version_and_replaces_local_authority(
    tmp_path: Path,
) -> None:
    original_payload = b'{"method":"Original bounded method."}'
    corrected_payload = b'{"method":"Corrected bounded method."}'
    original = _handle(original_payload)
    corrected = _handle(corrected_payload)
    store = tmp_path / "receipts.json"

    def original_response(_request: Request, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "receipt_id": "ccr_original",
                "manifest_byte_hash": original.manifest_byte_hash,
                "handle_binding": original.receipt_binding,
                "accepted": True,
                "status": "submitted-for-review",
            }
        )

    HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=original_response,
    ).submit(original_payload, handle=original)

    seen: list[Request] = []

    def correction_response(request: Request, *, timeout: float) -> _Response:
        del timeout
        seen.append(request)
        return _Response(
            {
                "receipt_id": "ccr_corrected",
                "manifest_byte_hash": corrected.manifest_byte_hash,
                "handle_binding": corrected.receipt_binding,
                "accepted": True,
                "status": "submitted-for-review",
            }
        )

    correction = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        replacement_receipt_id="ccr_original",
        opener=correction_response,
    )
    correction.submit(corrected_payload, handle=corrected)

    request = seen[0]
    assert request.full_url.endswith("/api/capability-contributions/correct")
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["x-dex-replaces-receipt"] == "ccr_original"
    ledger = json.loads(store.read_text(encoding="utf-8"))["receipts"]
    assert set(ledger) == {corrected.receipt_binding}
    assert ledger[corrected.receipt_binding]["receipt_id"] == "ccr_corrected"


def test_authenticated_delete_removes_all_saved_local_authority(tmp_path: Path) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)
    store = tmp_path / "receipts.json"

    def responder(request: Request, *, timeout: float) -> _Response:
        del timeout
        if request.full_url.endswith("/submit"):
            return _Response(
                {
                    "receipt_id": "ccr_delete",
                    "manifest_byte_hash": handle.manifest_byte_hash,
                    "handle_binding": handle.receipt_binding,
                    "accepted": True,
                    "status": "submitted-for-review",
                }
            )
        assert request.full_url.endswith("/api/capability-contributions/delete")
        assert request.data == b""
        return _Response(
            {
                "ok": True,
                "deleted_count": 1,
                "retention_disclosure": "A minimal tombstone remains for abuse prevention.",
            }
        )

    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=responder,
    )
    intake.submit(payload, handle=handle)

    receipt = intake.delete_all_saved()

    assert receipt.deleted_count == 1
    assert not store.exists()


def test_mismatched_hosted_receipt_fails_closed_without_local_acceptance(
    tmp_path: Path,
) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)

    def open_request(_request: Request, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            {
                "receipt_id": "ccr_789",
                "manifest_byte_hash": _hash(b"different"),
                "handle_binding": handle.receipt_binding,
                "accepted": True,
                "status": "submitted-for-review",
            }
        )

    store = tmp_path / "receipts.json"
    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=open_request,
    )

    with pytest.raises(HostedIntakeError, match="receipt"):
        intake.submit(payload, handle=handle)
    pending = json.loads(store.read_text(encoding="utf-8"))
    assert pending["receipts"][handle.receipt_binding]["status"] == "submitting"
    assert pending["receipts"][handle.receipt_binding]["receipt_id"] is None


def test_receipt_store_refuses_a_symlinked_parent_before_egress(tmp_path: Path) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    calls: list[Request] = []

    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=linked / "receipts.json",
        opener=lambda request, **_kwargs: calls.append(request),
    )

    with pytest.raises(HostedIntakeError, match="receipt store is unsafe"):
        intake.submit(payload, handle=handle)
    assert calls == []


def test_receipt_store_refuses_a_symlinked_ancestor_before_egress(tmp_path: Path) -> None:
    payload = b'{"method":"A bounded reusable method."}'
    handle = _handle(payload)
    real = tmp_path / "real"
    (real / "nested").mkdir(parents=True)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    calls: list[Request] = []

    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=linked / "nested" / "receipts.json",
        opener=lambda request, **_kwargs: calls.append(request),
    )

    with pytest.raises(HostedIntakeError, match="receipt store is unsafe"):
        intake.submit(payload, handle=handle)
    assert calls == []


def test_receipt_ledger_rejects_unbound_map_keys(tmp_path: Path) -> None:
    store = tmp_path / "receipts.json"
    store.write_text(
        json.dumps(
            {
                "receipts": {
                    "not-a-receipt-binding": {
                        "manifest_byte_hash": _hash(b"payload"),
                        "receipt_id": "ccr_123",
                        "status": "submitted-for-review",
                    }
                },
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=lambda *_args, **_kwargs: pytest.fail("invalid local state must not use network"),
    )

    with pytest.raises(HostedIntakeError, match="receipt store is invalid"):
        intake._load()


def test_withdraw_refuses_a_tampered_record_that_mixes_manifest_authority(
    tmp_path: Path,
) -> None:
    payload = b'{"method":"Approved method."}'
    handle = _handle(payload)
    store = tmp_path / "receipts.json"
    store.write_text(
        json.dumps(
            {
                "receipts": {
                    handle.receipt_binding: {
                        "manifest_byte_hash": _hash(b"different manifest"),
                        "receipt_id": "ccr_tampered",
                        "status": "submitted-for-review",
                    }
                },
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    calls: list[Request] = []
    intake = HostedContributionIntake(
        session_token=lambda: "hosted-session-token",
        receipt_store=store,
        opener=lambda request, **_kwargs: calls.append(request),
    )

    with pytest.raises(HostedIntakeError, match="manifest authority"):
        intake.withdraw(handle)

    assert calls == []


def test_heydex_credentials_are_lazy_bounded_and_reused_for_identity(tmp_path: Path) -> None:
    auth_path = tmp_path / "heydex-auth.json"
    credentials = HostedSessionCredentials(auth_path, now_ms=lambda: 2_000)
    assert not auth_path.exists()

    auth_path.write_text(
        json.dumps({"sessionToken": "linked-token", "timestamp": 1_000}),
        encoding="utf-8",
    )

    assert credentials.session_token() == "linked-token"
    assert credentials.contributor_secret() == b"linked-token"


def test_heydex_credentials_refuse_a_symlinked_parent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "heydex-auth.json").write_text(
        json.dumps({"sessionToken": "linked-token", "timestamp": 1_000}),
        encoding="utf-8",
    )
    linked = tmp_path / ".dex"
    linked.symlink_to(real, target_is_directory=True)

    credentials = HostedSessionCredentials(
        linked / "heydex-auth.json", now_ms=lambda: 2_000
    )
    with pytest.raises(HostedIntakeError, match="terminal link is unsafe"):
        credentials.session_token()


def test_real_cli_session_wires_hosted_contribution_without_reading_identity_early(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from capability_exchange.concierge.server import session_for_roots

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    approved = tmp_path / "brain"
    approved.mkdir()

    session = session_for_roots((approved,))
    try:
        assert isinstance(session.contribution_identity, HostedSessionCredentials)
        assert isinstance(session.contribution_intake, HostedContributionIntake)
        # The contribution door deliberately remains detached until the
        # account-free diagnosis reaches the Capability Map.
        assert session.journey.contribution_available is False
        assert not (tmp_path / "home" / ".dex" / "heydex-auth.json").exists()
    finally:
        session.terminate()


def test_real_cli_session_can_bind_a_correction_to_a_saved_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from capability_exchange.concierge.server import session_for_roots

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    approved = tmp_path / "brain"
    approved.mkdir()

    session = session_for_roots(
        (approved,),
        correction_receipt_id="ccr_saved",
    )
    try:
        assert isinstance(session.contribution_intake, HostedContributionIntake)
        assert session.contribution_intake.replacement_receipt_id == "ccr_saved"
    finally:
        session.terminate()
