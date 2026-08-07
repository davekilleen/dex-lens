"""Crash-log formatting that never includes private field values (G2).

The formatter keeps structure and discards values, fail closed:

- exception *type* names only — messages and args are never read into the
  record (a message is interpolated from arbitrary runtime values, so the
  schema has no field that could carry one);
- traceback frames as ``basename:line in function`` — no absolute paths
  (which can embed a real username), no locals, no variable values;
- the exception chain (``__cause__``/``__context__``) contributes type names
  and frames under the same rules.

Crash records are the only stored artifact on the M1 slice; their fields are
inventoried (``CrashLogRecord.*``) and deletable via the registered
``delete-crash-logs`` deletion path.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange import __version__
from capability_exchange.boundary.serialization import InventoriedModel

#: Cap on recorded frames and chained exceptions; a crash log is a pointer
#: for debugging, not a transcript.
_MAX_FRAMES = 50
_MAX_CHAIN = 10


class CrashLogRecord(InventoriedModel):
    """Structural description of a crash. Every field is inventoried."""

    timestamp: str
    exception_type: str
    frames: list[str]
    product_version: str


def _frames_for(exc: BaseException) -> list[str]:
    frames: list[str] = []
    for summary in traceback.extract_tb(exc.__traceback__)[:_MAX_FRAMES]:
        basename = os.path.basename(summary.filename or "<unknown>")
        frames.append(f"{basename}:{summary.lineno} in {summary.name}")
    return frames


def _chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def format_crash_record(exc: BaseException) -> CrashLogRecord:
    """Build the structural crash record for an exception (values excluded)."""
    frames: list[str] = []
    type_names: list[str] = []
    for link in _chain(exc):
        type_names.append(type(link).__qualname__)
        link_frames = _frames_for(link)
        if link is not exc and link_frames:
            frames.append(f"-- caused by {type(link).__qualname__} --")
        frames.extend(link_frames)
    return CrashLogRecord(
        timestamp=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        exception_type=" <- ".join(type_names) if len(type_names) > 1 else type_names[0],
        frames=frames,
        product_version=__version__,
    )


def write_crash_log(exc: BaseException, directory: Path) -> Path:
    """Format and persist a crash record; return the file path.

    Persistence goes through the typed boundary (``dump_for_storage``), so
    only inventoried, storage-declared fields can reach the file. The file
    name is unique per call and matches the ``delete-crash-logs`` glob.
    """
    record = format_crash_record(exc)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%f")
    path = directory / f"crashlog-{stamp}-{os.getpid()}.json"
    path.write_text(json.dumps(record.dump_for_storage(), indent=2), encoding="utf-8")
    return path
