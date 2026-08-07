"""G2 crash-log fixture: crash artifacts contain no private field values.

Canary values are planted in the exception message, exception args, local
variables, and an in-flight model instance; the formatted crash record and
the bytes written to disk must contain none of them. The formatter keeps
only structural information: exception type, code locations, timestamp,
product version.
"""

import json
from pathlib import Path

from capability_exchange.boundary.crashlog import (
    CrashLogRecord,
    format_crash_record,
    write_crash_log,
)
from capability_exchange.boundary.serialization import InventoriedModel

CANARY_SECRET = "CANARY-aws-AKIA9F31EXAMPLEKEY"
CANARY_PERSONAL = "CANARY-personal-Dave-Killeen-private-journal"
CANARY_PATH = "/Users/realname/private/notes.md"


class InFlightEvidence(InventoriedModel):
    excerpt: str


def crash_with_canaries() -> BaseException:
    """Raise and capture an exception saturated with canary values."""
    private_local = CANARY_PERSONAL  # planted local variable
    model = InFlightEvidence(excerpt=CANARY_SECRET)  # planted model field value
    try:
        raise ValueError(f"boom {CANARY_SECRET} while reading {CANARY_PATH}", private_local, model)
    except ValueError as exc:
        return exc


class TestCrashRecordExcludesPrivateValues:
    def test_no_canary_in_formatted_record(self) -> None:
        record = format_crash_record(crash_with_canaries())
        payload = json.dumps(record.dump_for_storage())
        for canary in (CANARY_SECRET, CANARY_PERSONAL, CANARY_PATH, "realname"):
            assert canary not in payload

    def test_exception_message_is_never_included(self) -> None:
        # Fail closed: messages are interpolated from arbitrary runtime
        # values, so the schema has no field that could carry one.
        assert "message" not in CrashLogRecord.model_fields
        record = format_crash_record(crash_with_canaries())
        assert "boom" not in json.dumps(record.dump_for_storage())

    def test_structural_information_is_present(self) -> None:
        record = format_crash_record(crash_with_canaries())
        assert record.exception_type == "ValueError"
        assert record.frames, "traceback frames must be recorded"
        assert any("crash_with_canaries" in frame for frame in record.frames)
        assert record.product_version
        assert record.timestamp

    def test_frames_use_basenames_not_absolute_paths(self) -> None:
        # Absolute paths can embed a real username; only basenames are kept.
        record = format_crash_record(crash_with_canaries())
        for frame in record.frames:
            assert not frame.startswith("/")
            assert "/Users/" not in frame and "/home/" not in frame


class TestCrashLogOnDisk:
    def test_written_bytes_contain_no_canaries(self, tmp_path: Path) -> None:
        log_path = write_crash_log(crash_with_canaries(), tmp_path)
        raw = log_path.read_bytes()
        for canary in (CANARY_SECRET, CANARY_PERSONAL, CANARY_PATH):
            assert canary.encode() not in raw

    def test_written_file_is_valid_stored_payload(self, tmp_path: Path) -> None:
        log_path = write_crash_log(crash_with_canaries(), tmp_path)
        payload = json.loads(log_path.read_text())
        # Exactly the storage-declared fields of CrashLogRecord, nothing more.
        assert set(payload) == set(CrashLogRecord.model_fields)
        assert payload["exception_type"] == "ValueError"

    def test_chained_exception_context_also_scrubbed(self, tmp_path: Path) -> None:
        try:
            try:
                raise RuntimeError(f"inner {CANARY_SECRET}")
            except RuntimeError as inner:
                raise ValueError(f"outer {CANARY_PERSONAL}") from inner
        except ValueError as exc:
            log_path = write_crash_log(exc, tmp_path)
        raw = log_path.read_text()
        assert CANARY_SECRET not in raw
        assert CANARY_PERSONAL not in raw
        assert "RuntimeError" in raw  # chain structure is kept, values are not
