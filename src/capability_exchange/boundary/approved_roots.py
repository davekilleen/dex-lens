"""Central invariants for an exact set of approved filesystem roots."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

__all__ = ["reject_overlapping_roots", "root_reference"]


def root_reference(root: str | os.PathLike[str]) -> str:
    """Return an opaque child-protocol binding for one canonical root."""

    canonical = Path(root).resolve(strict=False)
    return "root:sha256:" + hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()


def reject_overlapping_roots(roots: tuple[str | os.PathLike[str], ...]) -> None:
    """Reject any duplicate or ancestor/descendant root pair, in either order."""

    canonical = tuple(Path(root).resolve(strict=False) for root in roots)
    for index, first in enumerate(canonical):
        for second in canonical[index + 1 :]:
            if first == second or first in second.parents or second in first.parents:
                raise ValueError(
                    "approved roots overlap as an ancestor/descendant pair; "
                    "each path must belong to exactly one source"
                )
