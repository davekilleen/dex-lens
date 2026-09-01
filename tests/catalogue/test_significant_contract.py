"""Contract tests for significant capability coverage metadata.

These tests deliberately exercise the signed-catalogue boundary rather than
the report engine.  Family metadata is public release truth, so every branch
is closed and every cross-reference is checked against the same catalogue.
"""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from capability_exchange.catalogue.schema_contract import (
    MCP_TOOL_INVENTORY_KEYWORD,
    build_catalogue_schema,
    iter_catalogue_schema_errors,
)
from capability_exchange.catalogue.v2 import (
    UNIQUE_COMPONENT_IDENTITY_KEYWORD,
    CapabilityFamilyV2,
    CatalogueV2,
    McpServerCapabilityEntryV2,
)


def _job() -> dict[str, object]:
    return {
        "job_id": "plan-my-work",
        "label": "Plan my work",
        "description": "Choose a realistic plan from current commitments.",
        "confirmed_gap_signals": ["the plan does not reflect current commitments"],
    }


def _mcp(*, tools: list[str] | None = None, examples: list[str] | None = None) -> dict[str, object]:
    tools = tools if tools is not None else ["list_tasks", "add_note"]
    examples = examples if examples is not None else ["list_tasks"]
    return {
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
            {
                "level": "supported",
                "source": "test",
                "summary": "release evidence",
                "limitations": "local state is not inspected",
            }
        ],
        "release_provenance": "core-release",
        "server_name": "dex-work",
        "tool_count": len(tools),
        "example_tools": examples,
        "source_paths": ["core/mcp/work/server.py"],
        "tools": tools,
        "tool_inventory": "complete",
    }


def _family(
    *, members: list[str] | None = None, aliases: list[str] | None = None
) -> dict[str, object]:
    return {
        "family_id": "durable-task-continuity",
        "title": "Durable task continuity",
        "outcome": "Tasks stay connected from capture through completion.",
        "jobs": ["plan-my-work"],
        "aliases": aliases if aliases is not None else ["tasks-that-stick"],
        "member_capability_ids": members if members is not None else ["dex-work-mcp"],
        "components": [
            {"component_type": "capability", "capability_id": "dex-work-mcp"},
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work-mcp",
                "tool_name": "list_tasks",
            },
            {
                "component_type": "source-component",
                "component_id": "task-continuity",
            },
        ],
        "assessment": {"mode": "automatic", "profile": "mcp"},
    }


def _catalogue(
    *,
    capabilities: list[dict[str, object]] | None = None,
    aliases: list[dict[str, str]] | None = None,
    families: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "jobs_taxonomy": [_job()],
        "capabilities": capabilities if capabilities is not None else [_mcp()],
        "capability_aliases": aliases if aliases is not None else [],
        "capability_families": families if families is not None else [],
        "portable_brief": {
            "format": "markdown",
            "audience": "the person's own AI system",
            "safety_boundary": "guidance only; it changes nothing",
        },
    }


def _envelope(catalogue: dict[str, object]) -> dict[str, object]:
    """A schema-only envelope; signature bytes are irrelevant to this test."""
    return {
        "metadata": {
            "contract_version": "dex-lens-catalogue-v2",
            "catalog_version": 7,
            "produced_at": "2026-08-26T12:00:00Z",
            "expires_at": "2026-09-26T12:00:00Z",
            "producer": "Dex Core release pipeline",
            "core_release": "v1.97.0",
            "key_id": "dex-core-test",
        },
        "catalogue": catalogue,
        "signature": "schema-only-placeholder",
    }


def test_family_free_catalogue_defaults_aliases_and_families() -> None:
    catalogue = CatalogueV2.model_validate(
        {
            key: value
            for key, value in _catalogue().items()
            if key not in {"capability_aliases", "capability_families"}
        }
    )
    assert catalogue.capability_aliases == ()
    assert catalogue.capability_families == ()


def test_complete_mcp_inventory_requires_nonempty_unique_exact_tools() -> None:
    with pytest.raises(ValidationError):
        McpServerCapabilityEntryV2.model_validate(_mcp(tools=[], examples=[]))
    with pytest.raises(ValidationError):
        McpServerCapabilityEntryV2.model_validate(_mcp(tools=["list_tasks", "list_tasks"]))
    with pytest.raises(ValidationError):
        McpServerCapabilityEntryV2.model_validate(_mcp(tools=["list_tasks"], examples=["add_note"]))


def test_exported_schema_enforces_complete_mcp_inventory_semantics() -> None:
    valid = _envelope(_catalogue())
    assert not list(iter_catalogue_schema_errors(valid))

    mismatched_count = copy.deepcopy(valid)
    mismatched_count["catalogue"]["capabilities"][0]["tool_count"] = 1  # type: ignore[index]
    errors = list(iter_catalogue_schema_errors(mismatched_count))
    assert any("tool_count" in error.message for error in errors)

    missing_example = copy.deepcopy(valid)
    missing_example["catalogue"]["capabilities"][0]["example_tools"] = [  # type: ignore[index]
        "missing_tool"
    ]
    errors = list(iter_catalogue_schema_errors(missing_example))
    assert any("example" in error.message and "tools" in error.message for error in errors)

    # The same malformed payload is rejected by the runtime Pydantic path.
    with pytest.raises(ValidationError, match="complete MCP tool inventory"):
        CatalogueV2.model_validate(mismatched_count["catalogue"])


def test_exported_schema_fails_closed_if_mcp_inventory_rule_is_removed() -> None:
    envelope = _envelope(_catalogue())
    schema = build_catalogue_schema()
    schema["$defs"]["McpServerCapabilityEntryV2"].pop(  # type: ignore[index]
        MCP_TOOL_INVENTORY_KEYWORD
    )

    errors = list(iter_catalogue_schema_errors(envelope, schema=schema))

    assert any(
        error.validator == MCP_TOOL_INVENTORY_KEYWORD
        and "missing required" in error.message
        for error in errors
    ), errors


def test_mcp_server_names_are_unique_and_disjoint_from_capability_ids() -> None:
    second = _mcp()
    second["capability_id"] = "another-mcp"
    with pytest.raises(ValidationError, match="server_name"):
        CatalogueV2.model_validate(_catalogue(capabilities=[_mcp(), second]))

    colliding = _mcp()
    colliding["server_name"] = "dex-work-mcp"
    with pytest.raises(ValidationError, match="server_name.*capability"):
        CatalogueV2.model_validate(_catalogue(capabilities=[colliding]))


def test_sampled_mcp_inventory_remains_backward_compatible() -> None:
    payload = _mcp(tools=[], examples=["list_tasks"])
    payload["tool_count"] = 2
    payload.pop("tools")
    payload.pop("tool_inventory")
    entry = McpServerCapabilityEntryV2.model_validate(payload)
    assert entry.tools == ()
    assert entry.tool_inventory == "sampled"


def test_capability_alias_targets_are_known_and_do_not_collide() -> None:
    valid = CatalogueV2.model_validate(
        _catalogue(aliases=[{"alias": "work-tools", "capability_id": "dex-work-mcp"}])
    )
    assert valid.capability_aliases[0].capability_id == "dex-work-mcp"

    with pytest.raises(ValidationError, match="unknown.*capability"):
        CatalogueV2.model_validate(
            _catalogue(aliases=[{"alias": "work-tools", "capability_id": "missing-capability"}])
        )
    with pytest.raises(ValidationError, match="collid"):
        CatalogueV2.model_validate(
            _catalogue(aliases=[{"alias": "dex-work-mcp", "capability_id": "dex-work-mcp"}])
        )


def test_family_cross_references_and_typed_components_are_closed() -> None:
    catalogue = CatalogueV2.model_validate(_catalogue(families=[_family()]))
    family = catalogue.capability_families[0]
    assert isinstance(family, CapabilityFamilyV2)
    assert family.assessment.mode == "automatic"

    with pytest.raises(ValidationError, match="unknown.*member"):
        CatalogueV2.model_validate(
            _catalogue(families=[_family(members=["missing-capability"])])
        )

    with pytest.raises(ValidationError, match="complete.*tool inventory"):
        sampled_mcp = _mcp()
        sampled_mcp["tool_inventory"] = "sampled"
        CatalogueV2.model_validate(
            _catalogue(
                capabilities=[sampled_mcp],
                families=[_family()],
            )
        )


def test_family_components_must_reference_the_same_family_members() -> None:
    second_mcp = _mcp()
    second_mcp["capability_id"] = "dex-career-mcp"
    second_mcp["server_name"] = "dex-career"

    foreign_capability = _family()
    foreign_capability["components"] = [
        {"component_type": "capability", "capability_id": "dex-career-mcp"}
    ]
    with pytest.raises(ValidationError, match="non-member capability"):
        CatalogueV2.model_validate(
            _catalogue(
                capabilities=[_mcp(), second_mcp],
                families=[foreign_capability],
            )
        )

    foreign_tool = _family()
    foreign_tool["components"] = [
        {
            "component_type": "mcp-tool",
            "server_id": "dex-career",
            "tool_name": "list_tasks",
        }
    ]
    with pytest.raises(ValidationError, match="non-member MCP server"):
        CatalogueV2.model_validate(
            _catalogue(
                capabilities=[_mcp(), second_mcp],
                families=[foreign_tool],
            )
        )


def test_family_aliases_members_components_and_assessment_reject_duplicates_or_extras() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        CatalogueV2.model_validate(_catalogue(families=[_family(aliases=["same", "same"])]))
    with pytest.raises(ValidationError, match="duplicate"):
        CatalogueV2.model_validate(
            _catalogue(families=[_family(members=["dex-work-mcp", "dex-work-mcp"])])
        )
    extra = _family()
    extra["status"] = "available"
    with pytest.raises(ValidationError):
        CatalogueV2.model_validate(_catalogue(families=[extra]))


def test_family_ids_cannot_collide_with_capability_ids_or_aliases() -> None:
    colliding_capability = _family()
    colliding_capability["family_id"] = "dex-work-mcp"
    with pytest.raises(ValidationError, match="family.*canonical"):
        CatalogueV2.model_validate(_catalogue(families=[colliding_capability]))

    colliding_alias = _family()
    colliding_alias["family_id"] = "work-tools"
    with pytest.raises(ValidationError, match="family.*alias"):
        CatalogueV2.model_validate(
            _catalogue(
                aliases=[{"alias": "work-tools", "capability_id": "dex-work-mcp"}],
                families=[colliding_alias],
            )
        )


def test_nango_provider_and_assessment_branches_have_no_arbitrary_code() -> None:
    provider_family = _family()
    provider_family["components"] = [
        {
            "component_type": "nango-provider",
            "provider_id": "google-calendar",
            "source_package": "@nangohq/providers",
            "source_version": "0.70.5",
            "dex_support": "supported",
            "security_vetted": True,
        }
    ]
    provider_family["assessment"] = {"mode": "manual-only", "reason": "requires consent"}
    assert CatalogueV2.model_validate(_catalogue(families=[provider_family]))

    bad_provider = _family()
    bad_provider["components"] = [
        {
            "component_type": "nango-provider",
            "provider_id": "../../secret",
            "source_package": "wrong-package",
            "source_version": "latest",
            "dex_support": "supported",
            "security_vetted": False,
        }
    ]
    with pytest.raises(ValidationError):
        CatalogueV2.model_validate(_catalogue(families=[bad_provider]))

    bad_assessment = _family()
    bad_assessment["assessment"] = {"mode": "automatic", "profile": "run-shell-command"}
    with pytest.raises(ValidationError):
        CatalogueV2.model_validate(_catalogue(families=[bad_assessment]))


def test_schema_and_runtime_reject_duplicate_component_identity_with_changed_metadata() -> None:
    family = _family()
    family["components"] = [
        {
            "component_type": "nango-provider",
            "provider_id": "google-calendar",
            "source_package": "@nangohq/providers",
            "source_version": "0.70.5",
            "dex_support": "supported",
            "security_vetted": True,
        },
        {
            "component_type": "nango-provider",
            "provider_id": "google-calendar",
            "source_package": "@nangohq/providers",
            "source_version": "0.70.5",
            "dex_support": "unsupported",
            "security_vetted": False,
        },
    ]
    catalogue = _catalogue(families=[family])

    with pytest.raises(ValidationError, match="duplicate component"):
        CatalogueV2.model_validate(catalogue)
    assert any(
        "duplicate capability component identity" in error.message
        for error in iter_catalogue_schema_errors(_envelope(catalogue))
    )

    schema = build_catalogue_schema()
    schema["$defs"]["CapabilityFamilyV2"]["properties"]["components"].pop(  # type: ignore[index]
        UNIQUE_COMPONENT_IDENTITY_KEYWORD
    )
    assert any(
        UNIQUE_COMPONENT_IDENTITY_KEYWORD in error.message
        for error in iter_catalogue_schema_errors(_envelope(_catalogue()), schema=schema)
    )


def test_schema_only_payload_is_json_serializable() -> None:
    # Keep the schema contract test honest about the wire shape it hands to
    # the custom validator.
    assert json.loads(json.dumps(_envelope(_catalogue())))
