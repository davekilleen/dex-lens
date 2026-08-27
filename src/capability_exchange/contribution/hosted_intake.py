"""Exact-byte HTTPS adapter for the hosted Capability Exchange intake."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, StrictBool, model_validator

from capability_exchange.boundary.deletion import delete_hosted_contribution_receipts
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.concierge.journey import (
    ContributionHandle,
    SubmissionReceipt,
    WithdrawalReceipt,
)

DEFAULT_INTAKE_BASE_URL = "https://api.heydex.ai"
MAX_RESPONSE_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0
AUTH_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
_RECEIPT_ID = re.compile(r"^ccr_[a-zA-Z0-9]{1,124}$")
_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Never carry contribution authority to a redirected destination."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_DEFAULT_OPENER = urllib.request.build_opener(_RefuseRedirects).open


def _has_symlinked_ancestor(path: Path) -> bool:
    candidate = path
    while candidate != candidate.parent:
        if candidate.is_symlink():
            return True
        candidate = candidate.parent
    return False


class HostedIntakeError(RuntimeError):
    """The hosted intake did not prove the exact requested operation."""


class HostedAuthorizationControl(InventoriedModel):
    """Typed ephemeral bearer credential for the pinned intake host."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bearer_token: str = Field(min_length=1, max_length=8_192, repr=False)


class HostedCorrectionControl(InventoriedModel):
    """Typed reference to the prior contribution replaced by a correction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replacement_receipt_id: str = Field(
        pattern=r"^ccr_[a-zA-Z0-9]{1,124}$"
    )


class HostedSubmissionControl(InventoriedModel):
    """Closed non-body metadata for one approved hosted submission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_byte_hash: str = Field(pattern=_HASH_PATTERN)
    consent_hash: str = Field(pattern=_HASH_PATTERN)
    receipt_binding: str = Field(pattern=_HASH_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=128)
    permission_review: StrictBool
    permission_storage: StrictBool
    permission_moderation: StrictBool
    permission_attribution: StrictBool
    permission_reuse: StrictBool
    permission_distribution: StrictBool

    @classmethod
    def from_handle(cls, handle: ContributionHandle) -> HostedSubmissionControl:
        permissions = handle.permissions
        return cls(
            manifest_byte_hash=handle.manifest_byte_hash,
            consent_hash=handle.consent_hash,
            receipt_binding=handle.receipt_binding,
            idempotency_key=handle.idempotency_key,
            permission_review=permissions.review,
            permission_storage=permissions.storage,
            permission_moderation=permissions.moderation,
            permission_attribution=permissions.attribution,
            permission_reuse=permissions.reuse,
            permission_distribution=permissions.distribution,
        )


class HostedWithdrawalControl(InventoriedModel):
    """Closed non-body metadata for one bound hosted withdrawal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: str | None = Field(
        default=None, pattern=r"^ccr_[a-zA-Z0-9]{1,124}$"
    )
    manifest_byte_hash: str = Field(pattern=_HASH_PATTERN)
    receipt_binding: str = Field(pattern=_HASH_PATTERN)


class HostedReceiptRecord(InventoriedModel):
    """Minimal durable local authority needed for later self-service withdrawal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_byte_hash: str = Field(pattern=_HASH_PATTERN)
    receipt_id: str | None = Field(
        default=None, pattern=r"^ccr_[a-zA-Z0-9]{1,124}$"
    )
    status: Literal["submitting", "submitted-for-review", "withdrawn"]


class HostedReceiptLedger(InventoriedModel):
    """Versioned local receipt map; no disclosure bytes or identity are retained."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipts: dict[str, HostedReceiptRecord]
    schema_version: Literal[1] = 1

    @classmethod
    def empty(cls) -> HostedReceiptLedger:
        return cls(receipts={})

    @model_validator(mode="after")
    def _bounded_receipt_bindings(self) -> HostedReceiptLedger:
        if len(self.receipts) > 128 or any(
            re.fullmatch(_HASH_PATTERN, binding) is None for binding in self.receipts
        ):
            raise ValueError("hosted receipt ledger bindings are invalid")
        return self


class HostedContributionStatus(InventoriedModel):
    """Validated hosted state shown to the contributor, never stored locally."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: str = Field(pattern=r"^ccr_[a-zA-Z0-9]{1,124}$")
    manifest_byte_hash: str = Field(pattern=_HASH_PATTERN)
    status: Literal[
        "submitted-for-review",
        "changes-requested",
        "rejected",
        "eligible-for-core-consideration",
        "withdrawn",
    ]
    created_at: int = Field(ge=0)
    updated_at: int = Field(ge=0)
    withdrawn_at: int | None = Field(default=None, ge=0)
    deleted_at: int | None = Field(default=None, ge=0)
    replaces_receipt_id: str | None = Field(
        default=None,
        pattern=r"^ccr_[a-zA-Z0-9]{1,124}$",
    )
    moderation_decision: str | None = Field(default=None, max_length=128)
    moderation_reason: str | None = Field(default=None, max_length=512)


class HostedDeletionReceipt(InventoriedModel):
    """Exact account-deletion confirmation returned by hosted intake."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: StrictBool
    deleted_count: int = Field(ge=0)
    retention_disclosure: str = Field(min_length=1, max_length=2_048)


class HostedSessionCredentials:
    """Lazily reuse the user-controlled Heydex terminal link."""

    def __init__(
        self,
        auth_path: Path | None = None,
        *,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self._auth_path = auth_path or (Path.home() / ".dex" / "heydex-auth.json")
        self._now_ms = now_ms

    def session_token(self) -> str:
        try:
            if (
                _has_symlinked_ancestor(self._auth_path.parent)
                or self._auth_path.is_symlink()
                or self._auth_path.stat().st_size > MAX_RESPONSE_BYTES
            ):
                raise HostedIntakeError("the Heydex terminal link is unsafe")
            value = json.loads(self._auth_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HostedIntakeError(
                "link this terminal at https://heydex.ai/connect/?cli=true before contributing"
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostedIntakeError("the Heydex terminal link is unreadable") from exc
        if not isinstance(value, dict):
            raise HostedIntakeError("the Heydex terminal link is invalid")
        token = value.get("sessionToken")
        timestamp = value.get("timestamp")
        now_ms = self._now_ms()
        if (
            not isinstance(token, str)
            or not token
            or any(character.isspace() for character in token)
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or now_ms - int(timestamp) > AUTH_MAX_AGE_MS
            or now_ms < int(timestamp)
        ):
            raise HostedIntakeError(
                "the Heydex terminal link has expired; create a new code at "
                "https://heydex.ai/connect/?cli=true"
            )
        return token

    def contributor_secret(self) -> bytes:
        """Derive local pseudonymous provenance only after contribution approval."""

        return self.session_token().encode("utf-8")


def _validated_base_url(value: str) -> str:
    if value not in {DEFAULT_INTAKE_BASE_URL, DEFAULT_INTAKE_BASE_URL + "/"}:
        raise ValueError("hosted contribution intake must use the pinned HTTPS host")
    return DEFAULT_INTAKE_BASE_URL


def _boolean(value: bool | None) -> str:
    if type(value) is not bool:
        raise HostedIntakeError("contribution permissions are unresolved")
    return "true" if value else "false"


class HostedContributionIntake:
    """Send only approved bytes and retain only a bounded local control receipt."""

    def __init__(
        self,
        *,
        session_token: Callable[[], str],
        receipt_store: Path,
        base_url: str = DEFAULT_INTAKE_BASE_URL,
        replacement_receipt_id: str | None = None,
        opener: Callable[..., object] = _DEFAULT_OPENER,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._session_token = session_token
        self._receipt_store = receipt_store.expanduser()
        self._base_url = _validated_base_url(base_url)
        if replacement_receipt_id is not None and _RECEIPT_ID.fullmatch(
            replacement_receipt_id
        ) is None:
            raise ValueError("replacement contribution receipt is invalid")
        self._replacement_receipt_id = replacement_receipt_id
        self._opener = opener
        self._timeout = timeout

    def _authorization(self) -> str:
        token = self._session_token()
        if not isinstance(token, str) or not token.strip() or any(ch.isspace() for ch in token):
            raise HostedIntakeError("a linked Heydex terminal session is required")
        control = HostedAuthorizationControl(bearer_token=token).dump_for_transmission()
        return "Bearer " + str(control["bearer_token"])

    def _request(
        self,
        path: str,
        *,
        data: bytes | None,
        headers: dict[str, str],
        method: Literal["GET", "POST"] = "POST",
    ) -> dict[str, object]:
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            headers={"Accept": "application/json", **headers},
            method=method,
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:  # type: ignore[attr-defined]
                status = getattr(response, "status", 200)
                final_url = getattr(response, "geturl", lambda: request.full_url)()
                if final_url is not None and final_url != request.full_url:
                    raise HostedIntakeError("hosted contribution intake refused a redirect")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as exc:
            raise HostedIntakeError("hosted contribution intake was unavailable") from exc
        if status != 200 or len(raw) > MAX_RESPONSE_BYTES:
            raise HostedIntakeError("hosted contribution intake returned an invalid response")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise HostedIntakeError(
                "hosted contribution intake returned an invalid receipt"
            ) from exc
        if not isinstance(payload, dict):
            raise HostedIntakeError("hosted contribution intake returned an invalid receipt")
        return payload

    @staticmethod
    def _submission_headers(handle: ContributionHandle) -> dict[str, str]:
        control = HostedSubmissionControl.from_handle(handle).dump_for_transmission()
        return {
            "Content-Type": "application/json; charset=utf-8",
            "X-Dex-Manifest-Hash": str(control["manifest_byte_hash"]),
            "X-Dex-Consent-Hash": str(control["consent_hash"]),
            "X-Dex-Receipt-Binding": str(control["receipt_binding"]),
            "X-Dex-Idempotency-Key": str(control["idempotency_key"]),
            "X-Dex-Permission-Review": _boolean(control["permission_review"]),
            "X-Dex-Permission-Storage": _boolean(control["permission_storage"]),
            "X-Dex-Permission-Moderation": _boolean(control["permission_moderation"]),
            "X-Dex-Permission-Attribution": _boolean(control["permission_attribution"]),
            "X-Dex-Permission-Reuse": _boolean(control["permission_reuse"]),
            "X-Dex-Permission-Distribution": _boolean(control["permission_distribution"]),
        }

    def submit(self, payload: bytes, /, *, handle: ContributionHandle) -> SubmissionReceipt:
        if type(payload) is not bytes or not payload:
            raise HostedIntakeError("contribution payload must be exact non-empty bytes")
        payload_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        if payload_hash != handle.manifest_byte_hash:
            raise HostedIntakeError(
                "contribution payload does not match the approved manifest hash"
            )
        self._require_safe_receipt_path()
        replacement: tuple[str, HostedReceiptRecord] | None = None
        if self._replacement_receipt_id is not None:
            replacement = self._saved_record(self._replacement_receipt_id)
        self._record(
            handle.receipt_binding,
            HostedReceiptRecord(
                manifest_byte_hash=handle.manifest_byte_hash,
                status="submitting",
            ),
        )
        headers = self._submission_headers(handle)
        headers["Authorization"] = self._authorization()
        if self._replacement_receipt_id is not None:
            correction = HostedCorrectionControl(
                replacement_receipt_id=self._replacement_receipt_id
            ).dump_for_transmission()
            headers["X-Dex-Replaces-Receipt"] = str(
                correction["replacement_receipt_id"]
            )
        response = self._request(
            (
                "/api/capability-contributions/correct"
                if self._replacement_receipt_id is not None
                else "/api/capability-contributions/submit"
            ),
            data=payload,
            headers=headers,
        )
        receipt_id = response.get("receipt_id")
        exact = (
            isinstance(receipt_id, str)
            and _RECEIPT_ID.fullmatch(receipt_id) is not None
            and response.get("manifest_byte_hash") == handle.manifest_byte_hash
            and response.get("handle_binding") == handle.receipt_binding
            and response.get("accepted") is True
            and type(response.get("accepted")) is bool
            and response.get("status") == "submitted-for-review"
        )
        if not exact:
            raise HostedIntakeError("hosted contribution receipt was not exact and affirmative")
        self._record(
            handle.receipt_binding,
            HostedReceiptRecord(
                manifest_byte_hash=handle.manifest_byte_hash,
                receipt_id=receipt_id,
                status="submitted-for-review",
            ),
        )
        if replacement is not None:
            self._forget(replacement[0])
        return SubmissionReceipt(
            manifest_byte_hash=handle.manifest_byte_hash,
            handle_binding=handle.receipt_binding,
            accepted=True,
        )

    def withdraw(self, handle: ContributionHandle, /) -> WithdrawalReceipt:
        existing = self._load().receipts.get(handle.receipt_binding)
        if existing is None:
            raise HostedIntakeError("no bound hosted receipt exists for this contribution")
        if existing.manifest_byte_hash != handle.manifest_byte_hash:
            raise HostedIntakeError(
                "saved contribution receipt does not match the manifest authority"
            )
        return self._withdraw_record(handle.receipt_binding, existing)

    def has_durable_withdrawal_authority(
        self, handle: ContributionHandle, /
    ) -> bool:
        """Prove an exact accepted receipt survives for later self-service use."""

        try:
            existing = self._load().receipts.get(handle.receipt_binding)
        except HostedIntakeError:
            return False
        return bool(
            existing is not None
            and existing.manifest_byte_hash == handle.manifest_byte_hash
            and existing.receipt_id is not None
            and existing.status == "submitted-for-review"
        )

    @property
    def replacement_receipt_id(self) -> str | None:
        """Receipt this fresh, fully reviewed contribution will replace."""

        return self._replacement_receipt_id

    def saved_receipts(self) -> tuple[tuple[str, str], ...]:
        """List minimal local receipt controls without contacting the service."""

        return tuple(
            sorted(
                (record.receipt_id, record.status)
                for record in self._load().receipts.values()
                if record.receipt_id is not None
            )
        )

    def status_saved(self, receipt_id: str) -> HostedContributionStatus:
        """Fetch one saved receipt's hosted moderation state in a fresh process."""

        binding, record = self._saved_record(receipt_id)
        response = self._request(
            "/api/capability-contributions/status",
            data=None,
            headers={
                "Authorization": self._authorization(),
                "X-Dex-Receipt-Id": receipt_id,
                "X-Dex-Receipt-Binding": binding,
            },
            method="GET",
        )
        try:
            status = HostedContributionStatus.model_validate(response)
        except (TypeError, ValueError) as exc:
            raise HostedIntakeError("hosted contribution status was invalid") from exc
        if (
            status.receipt_id != receipt_id
            or status.manifest_byte_hash != record.manifest_byte_hash
        ):
            raise HostedIntakeError("hosted contribution status was not bound to the receipt")
        return status

    def withdraw_saved(self, receipt_id: str) -> WithdrawalReceipt:
        """Withdraw a saved receipt without reconstructing an in-memory journey."""

        binding, record = self._saved_record(receipt_id)
        return self._withdraw_record(binding, record)

    def delete_all_saved(self) -> HostedDeletionReceipt:
        """Delete every hosted contribution for the linked contributor account."""

        response = self._request(
            "/api/capability-contributions/delete",
            data=b"",
            headers={"Authorization": self._authorization()},
        )
        try:
            receipt = HostedDeletionReceipt.model_validate(response)
        except (TypeError, ValueError) as exc:
            raise HostedIntakeError("hosted contribution deletion receipt was invalid") from exc
        if receipt.ok is not True or type(receipt.ok) is not bool:
            raise HostedIntakeError("hosted contribution deletion was not affirmative")
        self._delete_local_store()
        return receipt

    def _saved_record(self, receipt_id: str) -> tuple[str, HostedReceiptRecord]:
        if _RECEIPT_ID.fullmatch(receipt_id) is None:
            raise HostedIntakeError("saved contribution receipt is invalid")
        matches = [
            (binding, record)
            for binding, record in self._load().receipts.items()
            if record.receipt_id == receipt_id
        ]
        if len(matches) != 1:
            raise HostedIntakeError("no unique saved hosted receipt exists")
        return matches[0]

    def _withdraw_record(
        self,
        binding: str,
        existing: HostedReceiptRecord,
    ) -> WithdrawalReceipt:
        control = HostedWithdrawalControl(
            receipt_id=existing.receipt_id,
            manifest_byte_hash=existing.manifest_byte_hash,
            receipt_binding=binding,
        ).dump_for_transmission()
        raw_receipt_id = control["receipt_id"]
        receipt_id = raw_receipt_id if isinstance(raw_receipt_id, str) else None
        headers = {
            "Authorization": self._authorization(),
            "X-Dex-Manifest-Hash": str(control["manifest_byte_hash"]),
            "X-Dex-Receipt-Binding": str(control["receipt_binding"]),
        }
        if receipt_id is not None:
            headers["X-Dex-Receipt-Id"] = receipt_id
        response = self._request(
            "/api/capability-contributions/withdraw",
            data=b"",
            headers=headers,
        )
        response_receipt_id = response.get("receipt_id")
        exact = (
            isinstance(response_receipt_id, str)
            and _RECEIPT_ID.fullmatch(response_receipt_id) is not None
            and (receipt_id is None or response_receipt_id == receipt_id)
            and response.get("manifest_byte_hash") == existing.manifest_byte_hash
            and response.get("handle_binding") == binding
            and response.get("withdrawn") is True
            and type(response.get("withdrawn")) is bool
            and response.get("status") == "withdrawn"
        )
        if not exact:
            raise HostedIntakeError("hosted withdrawal receipt was not exact and affirmative")
        self._forget(binding)
        return WithdrawalReceipt(
            manifest_byte_hash=existing.manifest_byte_hash,
            handle_binding=binding,
            withdrawn=True,
        )

    def _load(self) -> HostedReceiptLedger:
        path = self._receipt_store
        self._require_safe_receipt_path()
        try:
            if path.is_symlink() or path.stat().st_size > MAX_RESPONSE_BYTES:
                raise HostedIntakeError("the local hosted receipt store is unsafe")
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return HostedReceiptLedger.empty()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostedIntakeError("the local hosted receipt store is unreadable") from exc
        try:
            return HostedReceiptLedger.model_validate(value)
        except (TypeError, ValueError) as exc:
            raise HostedIntakeError("the local hosted receipt store is invalid") from exc

    def _record(self, binding: str, receipt: HostedReceiptRecord) -> None:
        current = self._load()
        receipts = dict(current.receipts)
        receipts[binding] = receipt
        self._write_ledger(HostedReceiptLedger(receipts=receipts))

    def _forget(self, binding: str) -> None:
        current = self._load()
        receipts = dict(current.receipts)
        receipts.pop(binding, None)
        if not receipts:
            delete_hosted_contribution_receipts(self._receipt_store.parent)
            if self._receipt_store.exists():
                try:
                    size = self._receipt_store.stat().st_size
                    with self._receipt_store.open("r+b") as handle:
                        handle.write(b"\0" * size)
                        handle.flush()
                        os.fsync(handle.fileno())
                except OSError:
                    pass
                self._receipt_store.unlink(missing_ok=True)
            if self._receipt_store.exists():
                raise HostedIntakeError(
                    "the local hosted receipt authority could not be deleted"
                )
            return
        self._write_ledger(HostedReceiptLedger(receipts=receipts))

    def _delete_local_store(self) -> None:
        delete_hosted_contribution_receipts(self._receipt_store.parent)
        if self._receipt_store.exists():
            try:
                size = self._receipt_store.stat().st_size
                with self._receipt_store.open("r+b") as handle:
                    handle.write(b"\0" * size)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError:
                pass
            self._receipt_store.unlink(missing_ok=True)
        if self._receipt_store.exists():
            raise HostedIntakeError("the local hosted receipt authority could not be deleted")

    def _write_ledger(self, ledger: HostedReceiptLedger) -> None:
        raw = (
            json.dumps(
                ledger.dump_for_storage(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        path = self._receipt_store
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise HostedIntakeError("the local hosted receipt store is unsafe")
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _require_safe_receipt_path(self) -> None:
        if (
            _has_symlinked_ancestor(self._receipt_store.parent)
            or self._receipt_store.is_symlink()
        ):
            raise HostedIntakeError("the local hosted receipt store is unsafe")
