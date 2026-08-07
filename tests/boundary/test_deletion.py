"""G2 deletion paths: every stored field's deletion verifiably removes bytes."""

from pathlib import Path

import pytest

from capability_exchange.boundary.crashlog import write_crash_log
from capability_exchange.boundary.deletion import (
    DeletionVerificationError,
    UnknownDeletionPathError,
    registered_deletion_paths,
    run_deletion_path,
    verify_deletion_coverage,
)
from capability_exchange.boundary.inventory import load_packaged_inventory

CANARY = "CANARY-deletion-9c4e-SECRET"


def make_crash(canary: str) -> BaseException:
    try:
        raise ValueError(canary)
    except ValueError as exc:
        return exc


class TestDeletionRemovesBytes:
    def test_crash_log_deletion_removes_files(self, tmp_path: Path) -> None:
        first = write_crash_log(make_crash(CANARY), tmp_path)
        second = write_crash_log(make_crash(CANARY), tmp_path)
        assert first.exists() and second.exists()

        deleted = run_deletion_path("delete-crash-logs", tmp_path)

        assert not first.exists()
        assert not second.exists()
        assert set(deleted) == {first, second}
        # No crash-log bytes survive anywhere under the target directory.
        assert [p for p in tmp_path.rglob("*") if p.is_file()] == []

    def test_deletion_is_idempotent_on_empty_directory(self, tmp_path: Path) -> None:
        assert run_deletion_path("delete-crash-logs", tmp_path) == []
        assert run_deletion_path("delete-crash-logs", tmp_path) == []

    def test_deletion_on_missing_directory_is_a_clean_no_op(self, tmp_path: Path) -> None:
        assert run_deletion_path("delete-crash-logs", tmp_path / "never-created") == []

    def test_unknown_deletion_path_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(UnknownDeletionPathError):
            run_deletion_path("delete-nonexistent-store", tmp_path)

    def test_surviving_file_raises_verification_error(self, tmp_path: Path, monkeypatch) -> None:
        # Sabotage unlink so the file survives; deletion must refuse to
        # report success it cannot prove.
        log = write_crash_log(make_crash(CANARY), tmp_path)
        original_unlink = Path.unlink

        def sabotaged_unlink(self: Path, *args, **kwargs):
            if self == log:
                return None  # silently fail to delete
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", sabotaged_unlink)
        with pytest.raises(DeletionVerificationError):
            run_deletion_path("delete-crash-logs", tmp_path)


class TestRegistryCoversInventory:
    def test_every_stored_field_has_a_registered_deletion_path(self) -> None:
        problems = verify_deletion_coverage(load_packaged_inventory())
        assert problems == []

    def test_coverage_check_reports_missing_registration(self) -> None:
        from capability_exchange.boundary.inventory import (
            FieldEntry,
            Inventory,
            StorageDeclaration,
        )

        inv = Inventory(
            inventory_version=1,
            fields={
                "Ghost.blob": FieldEntry(
                    description="d",
                    collection="c",
                    derivation="n",
                    display="d",
                    storage=StorageDeclaration(location="somewhere", duration="forever"),
                    sharing="never",
                    deletion="delete-ghost-store",
                    audit="none",
                )
            },
        )
        problems = verify_deletion_coverage(inv)
        assert len(problems) == 1
        assert "Ghost.blob" in problems[0] and "delete-ghost-store" in problems[0]

    def test_registry_is_nonempty_and_named(self) -> None:
        assert "delete-crash-logs" in registered_deletion_paths()
