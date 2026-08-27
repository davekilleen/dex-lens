"""G2 deletion-path registry.

Every inventory entry that declares storage names a deletion path id; this
module maps each id to the function that removes the stored bytes. Deletion
verifies its own result: a file that survives raises
:class:`DeletionVerificationError` rather than reporting success it cannot
prove (fail closed).

Byte removal here means: overwrite the file contents with zeros, then unlink,
then verify absence. On copy-on-write or journaling filesystems the overwrite
is best-effort against old extents; the verified guarantee is that no live
path serves the bytes afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from capability_exchange.boundary.inventory import Inventory


class DeletionError(Exception):
    """Base class for deletion-path failures."""


class UnknownDeletionPathError(DeletionError):
    """The requested deletion path id is not registered. Fail closed."""


class DeletionVerificationError(DeletionError):
    """Deletion could not be verified: stored bytes may survive."""


#: A deletion function removes every stored artifact for its field(s) under
#: the given target directory and returns the paths it removed.
DeletionFunction = Callable[[Path], list[Path]]

_REGISTRY: dict[str, DeletionFunction] = {}


def register_deletion_path(deletion_id: str, fn: DeletionFunction) -> None:
    if deletion_id in _REGISTRY:
        raise DeletionError(f"deletion path {deletion_id!r} registered twice")
    _REGISTRY[deletion_id] = fn


def registered_deletion_paths() -> dict[str, DeletionFunction]:
    return dict(_REGISTRY)


def run_deletion_path(deletion_id: str, target: Path) -> list[Path]:
    """Invoke a registered deletion path and return the removed paths."""
    fn = _REGISTRY.get(deletion_id)
    if fn is None:
        raise UnknownDeletionPathError(
            f"no deletion function registered for {deletion_id!r}; "
            f"refusing to claim deletion that cannot be performed"
        )
    return fn(target)


def verify_deletion_coverage(inventory: Inventory) -> list[str]:
    """Report inventory entries whose deletion path is not registered.

    Used by tests and by ``scripts/check_inventory.py`` (the CI
    g2-inventory-check step): every stored field must map to a registered
    deletion function.
    """
    problems: list[str] = []
    for key, entry in inventory.fields.items():
        if entry.stores and entry.deletion not in _REGISTRY:
            problems.append(
                f"{key}: declares storage with deletion path {entry.deletion!r}, "
                f"but no deletion function is registered under that id"
            )
    return problems


def _remove_file_verified(path: Path) -> None:
    """Overwrite with zeros, unlink, and verify the path is gone."""
    try:
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(b"\0" * size)
            handle.flush()
    except OSError:
        # Overwrite is belt-and-braces; unlink below is the verified step.
        pass
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    if path.exists():
        raise DeletionVerificationError(f"{path} still exists after deletion")


#: Glob for crash-log files written by capability_exchange.boundary.crashlog.
CRASH_LOG_GLOB = "crashlog-*.json"
ADAPTATION_RECEIPT_GLOB = "receipt-*.json"
ADAPTATION_RECOVERY_GLOB = "recovery-*.json"
ADAPTATION_JOURNAL_GLOB = "transaction-*.json"
ADAPTATION_OUTCOME_EVIDENCE_GLOB = "outcome-*.json"
PILOT_GATE_EVIDENCE_GLOB = "pilot-build-gate*.json"
TABLETOP_EVIDENCE_GLOB = "*-tabletop-evidence.json"

#: Cache file written by capability_exchange.catalogue.v2.VerifiedCatalogueStore.
LENS_CATALOGUE_CACHE_FILE = "lens-catalogue-v2-cache.json"
LENS_CATALOGUE_SUBSCRIPTION_FILE = "lens-catalogue-v2-subscription.json"
DIAGNOSIS_RUN_DIR = "diagnosis-runs"


def delete_crash_logs(directory: Path) -> list[Path]:
    """Deletion path ``delete-crash-logs``: remove all crash-log files.

    Covers every stored ``CrashLogRecord`` field (the whole record lives in
    one JSON file per crash). Missing directory or no files is a clean no-op;
    a surviving file raises :class:`DeletionVerificationError`.
    """
    if not directory.is_dir():
        return []
    removed: list[Path] = []
    for path in sorted(directory.glob(CRASH_LOG_GLOB)):
        _remove_file_verified(path)
        removed.append(path)
    return removed


register_deletion_path("delete-crash-logs", delete_crash_logs)


def _delete_matching(directory: Path, pattern: str) -> list[Path]:
    if not directory.is_dir():
        return []
    removed: list[Path] = []
    for path in sorted(directory.glob(pattern)):
        _remove_file_verified(path)
        removed.append(path)
    return removed


def delete_adaptation_receipts(directory: Path) -> list[Path]:
    """Remove every standard local M4 receipt under ``directory``."""

    return _delete_matching(directory, ADAPTATION_RECEIPT_GLOB)


def delete_adaptation_recovery(directory: Path) -> list[Path]:
    """Remove every M4 recovery manifest under ``directory``."""

    return _delete_matching(directory, ADAPTATION_RECOVERY_GLOB)


def delete_adaptation_journals(directory: Path) -> list[Path]:
    """Remove every M4 crash-recovery journal under ``directory``."""

    return _delete_matching(directory, ADAPTATION_JOURNAL_GLOB)


def delete_adaptation_state(directory: Path) -> list[Path]:
    """Remove core-owned T7 outcome evidence under ``directory``."""

    evidence = directory / "outcome-evidence"
    return _delete_matching(evidence, ADAPTATION_OUTCOME_EVIDENCE_GLOB)


register_deletion_path("delete-adaptation-receipts", delete_adaptation_receipts)
register_deletion_path("delete-adaptation-recovery", delete_adaptation_recovery)
register_deletion_path("delete-adaptation-journals", delete_adaptation_journals)
register_deletion_path("delete-adaptation-state", delete_adaptation_state)


def delete_pilot_gate_evidence(directory: Path) -> list[Path]:
    """Remove exact-build pilot gate evidence artifacts."""

    return _delete_matching(directory, PILOT_GATE_EVIDENCE_GLOB)


register_deletion_path("delete-pilot-gate-evidence", delete_pilot_gate_evidence)


def delete_tabletop_evidence(directory: Path) -> list[Path]:
    """Remove persisted synthetic recovery tabletop evidence."""

    return _delete_matching(directory, TABLETOP_EVIDENCE_GLOB)


register_deletion_path("delete-tabletop-evidence", delete_tabletop_evidence)


def delete_lens_catalogue_cache(directory: Path) -> list[Path]:
    """Remove the verified public Dex catalogue cache."""

    return _delete_matching(directory, LENS_CATALOGUE_CACHE_FILE)


register_deletion_path("delete-lens-catalogue-cache", delete_lens_catalogue_cache)


def delete_lens_catalogue_subscription(directory: Path) -> list[Path]:
    """Remove the durable public-catalogue update subscription record."""

    return _delete_matching(directory, LENS_CATALOGUE_SUBSCRIPTION_FILE)


register_deletion_path(
    "delete-lens-catalogue-subscription",
    delete_lens_catalogue_subscription,
)


def delete_diagnosis_run_state(directory: Path) -> list[Path]:
    """Remove durable diagnosis checkpoints stored outside inspected roots."""

    target = directory / DIAGNOSIS_RUN_DIR
    if not target.exists():
        return []
    removed: list[Path] = []
    for path in sorted(target.rglob("*")):
        if path.is_file():
            _remove_file_verified(path)
            removed.append(path)
    return removed


register_deletion_path("delete-diagnosis-run-state", delete_diagnosis_run_state)
