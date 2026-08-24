"""Where a diagnosis lives after the conversation that produced it ends.

A second opinion that exists only in a chat window is gone by Friday. The
person cannot show it to anyone, cannot check next month whether they acted on
it, and the next run has nothing to compare against — so it repeats the same
findings as if they were new, which is how a recurring check becomes noise.

So every diagnosis ends as a dated Markdown file, and this module is where it
goes. Two properties matter more than anything else here:

- **It is never written inside the folder being inspected.** The read-only
  guarantee is the product's whole basis for being trusted with someone's
  system; a report dropped into their vault would break it in the most banal
  way possible. The directory is app storage, and
  :func:`require_app_storage_outside_roots` proves the separation rather than
  assuming it.
- **The file names itself by date**, so run N can find run N-1 without anyone
  remembering what it was called.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.catalogue.subscription import (
    default_lens_app_storage,
    require_app_storage_outside_roots,
)

__all__ = ["LensReportStore", "SavedReport", "default_report_directory"]

#: Sorts chronologically as text, carries no path separators, and survives a
#: case-insensitive filesystem. The trailing ``Z`` says the stamp is UTC, which
#: matters when someone compares two reports written either side of a flight.
_STAMP_FORMAT = "%Y-%m-%dT%H%M%SZ"

_SEPARATOR = "--"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_DEFAULT_LABEL = "diagnosis"


def default_report_directory(
    approved_roots: Iterable[Path] = (),
    *,
    environ: dict[str, str] | None = None,
) -> Path:
    """The reports directory, proven to sit outside every approved root.

    Derived from the same app-storage root the catalogue cache uses, so there
    is one place to look for everything Lens keeps and one guard protecting it.
    """
    roots = tuple(approved_roots)
    reports = default_lens_app_storage(roots, environ=environ).parent / "reports"
    require_app_storage_outside_roots(reports, roots)
    return reports


def _slug(value: str) -> str:
    """A filename-safe label, or the default when nothing survives."""
    slug = _SLUG_STRIP.sub("-", value.strip().lower()).strip("-")
    return slug[:60] or _DEFAULT_LABEL


def _title_of(markdown: str) -> str:
    """The report's own first heading, so a listing reads like the reports."""
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                return heading
    return ""


@dataclass(frozen=True)
class SavedReport:
    """One report on disk, with the facts a listing needs about it."""

    path: Path
    saved_at: datetime
    label: str
    title: str

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def listing_line(self) -> str:
        """One line a person can read without being told how to read it."""
        when = self.saved_at.strftime("%Y-%m-%d %H:%M UTC")
        title = self.title or "(no title)"
        return f"{when}  {self.label}  {title}"


class LensReportStore:
    """Read and write the dated diagnosis reports for this machine."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(
        self,
        markdown: str,
        *,
        label: str = _DEFAULT_LABEL,
        now: datetime | None = None,
    ) -> SavedReport:
        """Write one dated report and return where it landed.

        An empty report is refused rather than written. A zero-byte file dated
        today is worse than no file at all: the next run reads it as a baseline
        and concludes that nothing was found last time.
        """
        if not markdown.strip():
            raise ValueError("a report with no content is not a report")

        stamp = (now or datetime.now(UTC)).astimezone(UTC)
        slug = _slug(label)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._free_path(stamp, slug)
        path.write_text(markdown, encoding="utf-8")
        return SavedReport(
            path=path,
            saved_at=stamp.replace(microsecond=0),
            label=slug,
            title=_title_of(markdown),
        )

    def _free_path(self, stamp: datetime, slug: str) -> Path:
        """A path this second's report can have without overwriting another.

        Two runs in the same second are rare and entirely possible, and the
        one thing that must not happen is the second silently replacing the
        first: these files are the only record that the first run happened.
        """
        base = f"{stamp.strftime(_STAMP_FORMAT)}{_SEPARATOR}{slug}"
        candidate = self.directory / f"{base}.md"
        suffix = 2
        while candidate.exists():
            candidate = self.directory / f"{base}-{suffix}.md"
            suffix += 1
        return candidate

    def list(self, *, label: str | None = None) -> list[SavedReport]:
        """Every report, newest first, optionally narrowed to one label."""
        if not self.directory.is_dir():
            return []
        wanted = _slug(label) if label else None
        reports = [
            report
            for path in sorted(self.directory.glob("*.md"))
            if (report := self._describe(path)) is not None
            and (wanted is None or report.label == wanted)
        ]
        return sorted(reports, key=lambda report: report.saved_at, reverse=True)

    def last(self, *, label: str | None = None) -> SavedReport | None:
        """The most recent report, or ``None`` when this is the first run."""
        reports = self.list(label=label)
        return reports[0] if reports else None

    def _describe(self, path: Path) -> SavedReport | None:
        """One file as a report, dating it from its name where possible.

        A file whose name Lens did not write still gets listed, dated by its
        modification time. Hiding a report because its name is unfamiliar
        would quietly answer "what did the last run say?" with the wrong file.
        """
        stem = path.stem
        stamp_text, _, label = stem.partition(_SEPARATOR)
        try:
            saved_at = datetime.strptime(stamp_text, _STAMP_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            saved_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(microsecond=0)
            label = stem
        try:
            title = _title_of(path.read_text(encoding="utf-8"))
        except OSError:
            return None
        return SavedReport(
            path=path,
            saved_at=saved_at,
            label=label or _DEFAULT_LABEL,
            title=title,
        )
