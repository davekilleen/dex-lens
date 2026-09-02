"""Validate the report ledger against the exact signed catalogue it accounts for."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from capability_exchange.catalogue.v2 import SignedCatalogueEnvelopeV2
from capability_exchange.diagnosis.comparison import ComparisonLedger
from capability_exchange.diagnosis.observations import ObservationKind

__all__ = ["load_and_validate_ledger"]


def load_and_validate_ledger(
    path: Path,
    envelope: SignedCatalogueEnvelopeV2,
) -> tuple[ComparisonLedger | None, list[str]]:
    """Load one ledger and prove it accounts for this verified catalogue."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ledger = ComparisonLedger.model_validate(payload)
    except FileNotFoundError:
        return None, [f"no such comparison ledger: {path}"]
    except UnicodeDecodeError:
        return None, [f"the comparison ledger must be UTF-8 text: {path}"]
    except json.JSONDecodeError as exc:
        return None, [f"the comparison ledger is not valid JSON: {exc.msg}"]
    except OSError as exc:
        return None, [f"could not read the comparison ledger: {exc}"]
    except ValidationError as exc:
        return None, [f"the comparison ledger is incomplete: {exc.errors()[0]['msg']}"]

    signed_json = envelope._signed_json
    if signed_json is None:
        return None, ["the comparison ledger requires a signature-verified catalogue"]
    exact_sha = hashlib.sha256(signed_json.encode("utf-8")).hexdigest()
    if (
        ledger.catalogue_version != envelope.metadata.catalog_version
        or ledger.catalogue_sha256 != exact_sha
    ):
        return None, [
            "the comparison ledger does not belong to the exact verified catalogue "
            "used for this diagnosis"
        ]
    if ledger.version_distance is not None:
        release_evidence = tuple(
            sorted(
                {
                    reference
                    for item in ledger.local_entries
                    if item.kind is ObservationKind.RELEASE and item.identity == "dex-core"
                    for reference in item.evidence_references
                }
            )[:8]
        )
        if ledger.version_distance.evidence_references != release_evidence:
            return None, [
                "the version distance release evidence does not match the exact "
                "local Dex release observation"
            ]
    try:
        rebound = ComparisonLedger.for_catalogue(
            envelope.catalogue,
            catalogue_version=ledger.catalogue_version,
            catalogue_sha256=ledger.catalogue_sha256,
            capabilities=ledger.capabilities,
            entries=ledger.entries,
            ranked_recommendations=ledger.ranked_recommendations,
            mcp_tools_by_server=(
                ledger.mcp_tools_by_server if "mcp_tools_by_server" in payload else None
            ),
            family_entries=(
                ledger.family_entries if "family_entries" in payload else None
            ),
            version_distance=(
                ledger.version_distance if "version_distance" in payload else None
            ),
            local_entries=ledger.local_entries,
            reciprocal_answer=ledger.reciprocal_answer,
        )
    except ValidationError as exc:
        return None, [f"the comparison ledger is incomplete: {exc.errors()[0]['msg']}"]
    if (
        ledger.version_distance is not None
        and ledger.version_distance.current_version
        != getattr(envelope.metadata, "core_release", None)
    ):
        return None, ["the version distance does not match the exact catalogue release"]
    return rebound, []
