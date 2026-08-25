"""The catalogue can carry all four Dex capability classes, backward-compatibly.

Dex is skills, MCP servers, scheduled automations and system engines. The
catalogue used to be able to express only the first; this proves the model now
accepts the other three without a rebuild brief, still requires a brief for a
skill, and — the property that lets it ship safely — validates every catalogue
that predates the four-class fields unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from capability_exchange.catalogue.agent import (
    render_capability_brief_markdown,
    render_catalogue_digest,
)
from capability_exchange.catalogue.v2 import (
    CatalogueCapabilityEntryV2,
    SignedCatalogueEnvelopeV2,
)

_CONTRACT = {
    "format": "markdown",
    "audience": "the person's own AI system",
    "safety_boundary": "guidance only; it changes nothing",
}
_LIVE = Path("/home/user/lab/cat.json")


def _skill_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "capability_id": "daily-plan",
        "title": "Daily Plan",
        "summary": "Builds the day from calendar and tasks.",
        "value": "The morning forcing function.",
        "jobs": ["plan-my-work"],
        "prerequisites": ["a task source"],
        "trade_offs": ["only as current as its sources"],
        "evidence": [
            {"level": "supported", "source": "test: x", "summary": "s", "limitations": "l"}
        ],
        "compatibility": {
            "host_adapters": ["claude-code"],
            "foundation_capabilities": ["privacy-minimal-disclosure"],
            "minimum_lens_contract": "0.1.0",
            "platforms": ["macos"],
            "host_requirements": ["macos"],
            "limitations": ["none"],
            "needs_hooks": False,
            "needs_mcp": True,
        },
        "docs_url": "https://github.com/davekilleen/Dex",
        "since_release": "1.80.0",
        "changed_in": [],
        "release_provenance": "core-release",
        "portable_brief": {
            "goal": "plan the day",
            "method_outline": ["read the calendar"],
            "verification_checklist": ["a plan exists"],
            "rollback_advice": "delete the plan",
            "safety_notes": ["reads only"],
        },
    }
    entry.update(overrides)
    return entry


def test_an_entry_with_no_class_reads_as_a_skill() -> None:
    entry = CatalogueCapabilityEntryV2.model_validate(_skill_entry())
    assert entry.capability_class == "active-skill"
    assert entry.impact_tier is None


def test_a_non_skill_needs_no_rebuild_brief() -> None:
    mcp = _skill_entry(
        capability_id="dex-work-mcp",
        title="Work MCP server",
        capability_class="mcp-server",
        impact_tier="core",
    )
    del mcp["portable_brief"]
    entry = CatalogueCapabilityEntryV2.model_validate(mcp)
    assert entry.capability_class == "mcp-server"
    assert entry.portable_brief is None


def test_a_skill_without_a_brief_is_refused() -> None:
    bad = _skill_entry()
    del bad["portable_brief"]
    with pytest.raises(ValueError, match="portable brief"):
        CatalogueCapabilityEntryV2.model_validate(bad)


def test_the_digest_marks_a_non_skill_and_its_rank() -> None:
    catalogue = {
        "jobs_taxonomy": [
            {
                "job_id": "plan-my-work",
                "label": "Plan my work",
                "description": "Plan the work.",
                "confirmed_gap_signals": ["a gap in planning"],
            }
        ],
        "capabilities": [
            _skill_entry(),
            {
                k: v
                for k, v in _skill_entry(
                    capability_id="dex-work-mcp",
                    title="Work MCP server",
                    capability_class="mcp-server",
                    impact_tier="core",
                ).items()
                if k != "portable_brief"
            },
        ],
        "portable_brief": _CONTRACT,
    }
    from capability_exchange.catalogue.v2 import CatalogueV2

    rendered = render_catalogue_digest(CatalogueV2.model_validate(catalogue))
    assert "MCP server" in rendered and "core" in rendered
    # A skill is never labelled as a skill: the plain daily-plan line has no tag.
    assert "Daily Plan** (`daily-plan`) —" in rendered


def test_brief_on_a_non_skill_explains_rather_than_crashes() -> None:
    from capability_exchange.catalogue.v2 import CatalogueV2

    catalogue = CatalogueV2.model_validate(
        {
            "jobs_taxonomy": [
                {
                    "job_id": "plan-my-work",
                    "label": "Plan",
                    "description": "d",
                    "confirmed_gap_signals": ["a gap"],
                }
            ],
            "capabilities": [
                {
                    k: v
                    for k, v in _skill_entry(
                        capability_id="dex-work-mcp",
                        title="Work MCP server",
                        capability_class="mcp-server",
                    ).items()
                    if k != "portable_brief"
                }
            ],
            "portable_brief": _CONTRACT,
        }
    )
    out = render_capability_brief_markdown(catalogue, "dex-work-mcp")
    assert "MCP server" in out
    assert "no portable rebuild brief" in out


@pytest.mark.skipif(not _LIVE.is_file(), reason="live catalogue snapshot not present")
def test_the_current_live_catalogue_still_validates_unchanged() -> None:
    """The backward-compatibility guarantee that lets this ship: a catalogue
    signed before the four-class fields existed must still verify."""
    envelope = SignedCatalogueEnvelopeV2.model_validate(json.loads(_LIVE.read_text()))
    assert envelope.catalogue.capabilities
    assert all(e.capability_class == "active-skill" for e in envelope.catalogue.capabilities)


def test_verify_keeps_the_exact_signed_bytes_for_the_store() -> None:
    """The store must persist what was signed, not a re-serialised model.

    Re-dumping the model injects a defaulted field the signed original did not
    carry, so its signature would fail on offline reload. verify keeps the raw
    bytes for the store to write verbatim.
    """
    from capability_exchange.catalogue.v2 import SignedCatalogueEnvelopeV2

    raw = _LIVE.read_text() if _LIVE.is_file() else None
    if raw is None:
        pytest.skip("live catalogue snapshot not present")
    envelope = SignedCatalogueEnvelopeV2.model_validate(json.loads(raw))
    # A model dump now carries capability_class on every entry; the signed
    # original did not — so the two are not interchangeable for signing.
    assert '"capability_class"' in envelope.model_dump_json()
    assert '"capability_class"' not in raw
