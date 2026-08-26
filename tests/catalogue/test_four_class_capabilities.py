"""The catalogue carries all four Dex capability classes, backward-compatibly.

Dex is skills, MCP servers, scheduled automations and system engines. Under
the 0.1.9 contract an entry is one of five closed shapes: the legacy
skill-only shape every already-signed catalogue uses, or one of four
class-discriminated enriched shapes. This file proves the union routes each
shape to its model, that the skill-only fields stay skill-only, and that the
agent-facing renderings say what a non-skill is instead of crashing or
fabricating a rebuild.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from capability_exchange.catalogue.agent import (
    render_capability_brief_markdown,
    render_catalogue_digest,
)
from capability_exchange.catalogue.v2 import (
    ActiveSkillCapabilityEntryV2,
    CatalogueCapabilityEntryV2,
    CatalogueV2,
    LegacySkillCapabilityEntryV2,
    McpServerCapabilityEntryV2,
)

_CONTRACT = {
    "format": "markdown",
    "audience": "the person's own AI system",
    "safety_boundary": "guidance only; it changes nothing",
}

_ENTRY_ADAPTER: TypeAdapter = TypeAdapter(CatalogueCapabilityEntryV2)


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


def _mcp_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "capability_id": "dex-work-mcp",
        "capability_class": "mcp-server",
        "impact_tier": "core",
        "availability": "active",
        "title": "Work MCP server",
        "summary": "Task and project tools over MCP.",
        "value": "The system's hands for work items.",
        "jobs": ["plan-my-work"],
        "prerequisites": ["a running Dex install"],
        "trade_offs": ["only inside Dex"],
        "evidence": [
            {"level": "supported", "source": "test: x", "summary": "s", "limitations": "l"}
        ],
        "release_provenance": "core-release",
        "server_name": "dex-work",
        "tool_count": 12,
        "example_tools": ["list_tasks", "add_note"],
        "source_paths": ["core/mcp/work/server.py"],
    }
    entry.update(overrides)
    return entry


def test_an_entry_with_no_class_is_the_legacy_skill_shape() -> None:
    entry = _ENTRY_ADAPTER.validate_python(_skill_entry())
    assert isinstance(entry, LegacySkillCapabilityEntryV2)
    assert not hasattr(entry, "capability_class")


def test_an_enriched_skill_keeps_every_skill_field() -> None:
    entry = _ENTRY_ADAPTER.validate_python(
        _skill_entry(capability_class="active-skill", impact_tier="high", availability="active")
    )
    assert isinstance(entry, ActiveSkillCapabilityEntryV2)
    assert entry.portable_brief.goal == "plan the day"
    assert entry.compatibility.platforms == ("macos",)


def test_a_non_skill_carries_its_own_class_fields_and_no_skill_fields() -> None:
    entry = _ENTRY_ADAPTER.validate_python(_mcp_entry())
    assert isinstance(entry, McpServerCapabilityEntryV2)
    assert entry.tool_count == 12
    assert not hasattr(entry, "portable_brief")


def test_a_classed_non_skill_with_skill_fields_is_refused() -> None:
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(_mcp_entry(docs_url="https://example.invalid"))


def test_a_skill_without_a_brief_is_refused() -> None:
    bad = _skill_entry()
    del bad["portable_brief"]
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(bad)
    enriched_bad = _skill_entry(
        capability_class="active-skill", impact_tier="high", availability="active"
    )
    del enriched_bad["portable_brief"]
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(enriched_bad)


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
        "capabilities": [_skill_entry(), _mcp_entry()],
        "portable_brief": _CONTRACT,
    }

    rendered = render_catalogue_digest(CatalogueV2.model_validate(catalogue))
    assert "MCP server" in rendered and "core" in rendered
    # A skill is never labelled as a skill: the plain daily-plan line has no tag.
    assert "Daily Plan** (`daily-plan`) —" in rendered


def test_brief_on_a_non_skill_explains_rather_than_crashes() -> None:
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
            "capabilities": [_mcp_entry()],
            "portable_brief": _CONTRACT,
        }
    )
    out = render_capability_brief_markdown(catalogue, "dex-work-mcp")
    assert "MCP server" in out
    assert "no portable rebuild brief" in out
    # The MCP facts are rendered through the class model, not invented.
    assert "dex-work" in out and "12 tool(s)" in out
