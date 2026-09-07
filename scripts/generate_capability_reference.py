#!/usr/bin/env python3
"""Generate Lens's packaged fallback from one verified signed catalogue.

The fallback is deliberately not a second catalogue projection.  It embeds
the exact signed envelope and a small amount of provenance derived from that
envelope.  That keeps the normal Lens verifier authoritative and prevents a
hand-maintained summary from acquiring facts the signed source never carried.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from capability_exchange.catalogue.v2 import (  # noqa: E402
    CatalogueVerificationError,
    KeyRing,
    capability_class_of,
    default_keyring,
    verify_catalogue_envelope,
    verify_catalogue_envelope_for_stale_display,
)

REFERENCE_PATH = (
    SRC_ROOT / "capability_exchange" / "skill" / "dex-lens" / "dex-capabilities.json"
)
_REQUIRED_CLASSES = {
    "active-skill",
    "mcp-server",
    "scheduled-automation",
    "system-engine",
}
_NOTE = (
    "A release-bundled, signature-verifiable snapshot of Dex's full capability "
    "catalogue. It is a fallback for an older verified skills-only catalogue, "
    "not an overlay for a current enriched catalogue."
)


class CapabilityReferenceError(ValueError):
    """The signed source cannot become a safe packaged fallback."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _display_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def build_reference(
    raw_catalogue: str,
    *,
    keyring: KeyRing,
    allow_expired_source: bool = False,
) -> dict[str, Any]:
    """Verify ``raw_catalogue`` and derive the closed packaged wrapper.

    Normal generation enforces the catalogue's expiry.  ``--check`` may
    re-verify an older packaged snapshot for drift, so that path ignores only
    expiry while retaining signature, schema, contract and key checks.
    """
    if allow_expired_source:
        verified = verify_catalogue_envelope_for_stale_display(
            raw_catalogue,
            keyring=keyring,
        )
    else:
        verified = verify_catalogue_envelope(raw_catalogue, keyring=keyring)

    parsed_envelope = json.loads(raw_catalogue)
    present_classes = {
        capability_class_of(entry) for entry in verified.catalogue.capabilities
    }
    if present_classes != _REQUIRED_CLASSES:
        missing = sorted(_REQUIRED_CLASSES - present_classes)
        extra = sorted(present_classes - _REQUIRED_CLASSES)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise CapabilityReferenceError(
            "packaged fallback source must contain all four enriched capability "
            "classes (" + "; ".join(detail) + ")"
        )

    canonical_source = _canonical_json_bytes(parsed_envelope)
    # Re-load the canonical form so the generated wrapper is byte-stable even
    # when an equally valid source file uses different whitespace or key order.
    source_envelope = json.loads(canonical_source)
    return {
        "reference_version": 2,
        "source_catalogue": {
            "catalog_version": verified.metadata.catalog_version,
            "core_release": verified.metadata.core_release,
            "produced_at": _display_timestamp(verified.metadata.produced_at),
            "key_id": verified.metadata.key_id,
            "canonical_sha256": hashlib.sha256(canonical_source).hexdigest(),
        },
        "note": _NOTE,
        "signed_catalogue": source_envelope,
    }


def render_reference(
    raw_catalogue: str,
    *,
    keyring: KeyRing,
    allow_expired_source: bool = False,
) -> bytes:
    reference = build_reference(
        raw_catalogue,
        keyring=keyring,
        allow_expired_source=allow_expired_source,
    )
    return (json.dumps(reference, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _embedded_source(reference_path: Path) -> str:
    try:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        envelope = reference["signed_catalogue"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CapabilityReferenceError(
            f"cannot read the embedded signed catalogue from {reference_path}"
        ) from exc
    return _canonical_json_bytes(envelope).decode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        help="path to a signed Dex catalogue envelope (required when writing)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REFERENCE_PATH,
        help=f"generated reference path (default: {REFERENCE_PATH})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless output is the exact generated bytes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.input is not None:
            raw_catalogue = args.input.read_text(encoding="utf-8")
            allow_expired_source = False
        elif args.check:
            raw_catalogue = _embedded_source(args.output)
            allow_expired_source = True
        else:
            raise CapabilityReferenceError("--input is required when writing the fallback")

        generated = render_reference(
            raw_catalogue,
            keyring=default_keyring(),
            allow_expired_source=allow_expired_source,
        )
        if args.check:
            current = args.output.read_bytes()
            if current != generated:
                raise CapabilityReferenceError(
                    f"{args.output} has drifted; regenerate it with this script"
                )
            print(f"capability reference is exact generated output: {args.output}")
            return 0

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(generated)
        print(f"generated signature-verified capability reference: {args.output}")
        return 0
    except (CapabilityReferenceError, CatalogueVerificationError, OSError, ValueError) as exc:
        print(f"capability reference generation refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
