"""Complete machine-readable contract for Dex Lens catalogue producers.

JSON Schema Draft 2020-12 can require whole array items to be unique, but it
cannot express uniqueness by one field inside otherwise different objects.
The signed catalogue requires unique ``job_id`` and ``capability_id`` values,
so the exported contract uses one required Lens vocabulary keyword and ships
the reference validator for it. A consumer that does not support this dialect
has not validated the complete catalogue contract.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterator, Mapping
from typing import Any

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError

from capability_exchange.catalogue.v2 import (
    UNIQUE_BY_KEYWORD,
    UNIQUE_COMPONENT_IDENTITY_KEYWORD,
    SignedCatalogueEnvelopeV2,
)

CATALOGUE_SCHEMA_ID = "https://heydex.ai/catalogue/dex-lens/v2.schema.json"

# The Lens release floor a producer needs before it may publish enriched
# four-class entries. Core's preview guard reads this annotation from the
# exported schema to verify the compatible Lens floor.
MINIMUM_VERSION_KEYWORD = "x-dex-lens-minimum-version"
MINIMUM_LENS_VERSION = "0.1.9"
CONTRACT_STATUS_KEYWORD = "x-dex-lens-contract-status"
CONTRACT_STATUS = "unreleased-significant-family-preview"

# The five closed entry branches of the rollout-compatible union, in the
# order the exported ``oneOf`` declares them: the legacy skill-only shape
# every already-signed catalogue uses, then the four class-discriminated
# enriched shapes.
ENTRY_BRANCH_MODELS = (
    "LegacySkillCapabilityEntryV2",
    "ActiveSkillCapabilityEntryV2",
    "McpServerCapabilityEntryV2",
    "ScheduledAutomationCapabilityEntryV2",
    "SystemEngineCapabilityEntryV2",
)
CATALOGUE_SCHEMA_DIALECT_ID = (
    "https://heydex.ai/catalogue/dex-lens/v2-dialect.schema.json"
)
UNIQUE_BY_VOCABULARY_ID = (
    "https://heydex.ai/catalogue/dex-lens/vocab/unique-by"
)
MCP_TOOL_INVENTORY_KEYWORD = "x-dex-lens-mcp-tool-inventory"
MCP_TOOL_INVENTORY_VOCABULARY_ID = (
    "https://heydex.ai/catalogue/dex-lens/vocab/mcp-tool-inventory"
)
UNIQUE_COMPONENT_IDENTITY_VOCABULARY_ID = (
    "https://heydex.ai/catalogue/dex-lens/vocab/unique-component-identity"
)


def _validate_unique_by(
    _validator: Draft202012Validator,
    property_name: object,
    instance: object,
    schema: Mapping[str, Any],
) -> Iterator[ValidationError]:
    """Reject two array objects that reuse the configured identifier field."""
    if not isinstance(property_name, str) or not isinstance(instance, list):
        return

    seen: dict[str, int] = {}
    for index, item in enumerate(instance):
        if not isinstance(item, Mapping) or property_name not in item:
            continue
        try:
            marker = json.dumps(
                item[property_name],
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            # The structural schema reports non-JSON or wrongly typed values.
            continue
        first_index = seen.setdefault(marker, index)
        if first_index == index:
            continue
        yield ValidationError(
            (
                f"duplicate {property_name} {item[property_name]!r} "
                f"at indexes {first_index} and {index}"
            ),
            validator=UNIQUE_BY_KEYWORD,
            validator_value=property_name,
            instance=instance,
            schema=schema,
            path=deque((index, property_name)),
        )


def _validate_mcp_tool_inventory(
    _validator: Draft202012Validator,
    enabled: object,
    instance: object,
    schema: Mapping[str, Any],
) -> Iterator[ValidationError]:
    """Enforce the cross-field rules for a complete MCP tool inventory.

    JSON Schema can describe each field and can require array items to be
    unique, but it cannot express the relationship between ``tool_count``,
    ``tools`` and ``example_tools``.  This vocabulary keyword keeps the
    producer schema honest about the same relationship Pydantic enforces.
    """
    if enabled is not True or not isinstance(instance, Mapping):
        return
    if instance.get("tool_inventory") != "complete":
        return

    tools = instance.get("tools")
    if tools is None:
        yield ValidationError(
            "complete MCP tool inventory requires a non-empty tools list",
            validator=MCP_TOOL_INVENTORY_KEYWORD,
            validator_value=enabled,
            instance=instance,
            schema=schema,
            path=deque(("tools",)),
        )
        return
    if not isinstance(tools, list):
        # The structural schema reports the wrong type and item shape.
        return
    if not tools:
        yield ValidationError(
            "complete MCP tool inventory tools must be non-empty",
            validator=MCP_TOOL_INVENTORY_KEYWORD,
            validator_value=enabled,
            instance=instance,
            schema=schema,
            path=deque(("tools",)),
        )
    if all(isinstance(tool, str) for tool in tools) and len(set(tools)) != len(tools):
        yield ValidationError(
            "complete MCP tool inventory tools must be unique",
            validator=MCP_TOOL_INVENTORY_KEYWORD,
            validator_value=enabled,
            instance=instance,
            schema=schema,
            path=deque(("tools",)),
        )

    tool_count = instance.get("tool_count")
    if type(tool_count) is int and tool_count != len(tools):
        yield ValidationError(
            "complete MCP tool inventory tool_count must equal the number of tools "
            f"({tool_count} != {len(tools)})",
            validator=MCP_TOOL_INVENTORY_KEYWORD,
            validator_value=enabled,
            instance=instance,
            schema=schema,
            path=deque(("tool_count",)),
        )

    examples = instance.get("example_tools")
    if isinstance(examples, list) and all(isinstance(example, str) for example in examples):
        missing_examples = sorted(set(examples) - set(tools))
        if missing_examples:
            yield ValidationError(
                "complete MCP tool inventory example_tools must be a subset of tools: "
                + ", ".join(missing_examples),
                validator=MCP_TOOL_INVENTORY_KEYWORD,
                validator_value=enabled,
                instance=instance,
                schema=schema,
                path=deque(("example_tools",)),
            )


def _component_identity(item: Mapping[str, Any]) -> tuple[object, ...] | None:
    component_type = item.get("component_type")
    if component_type == "capability" and "capability_id" in item:
        return (component_type, item["capability_id"])
    if component_type == "mcp-tool" and {"server_id", "tool_name"} <= set(item):
        return (component_type, item["server_id"], item["tool_name"])
    if component_type == "nango-provider" and "provider_id" in item:
        return (component_type, item["provider_id"])
    if component_type == "source-component" and "component_id" in item:
        return (component_type, item["component_id"])
    return None


def _validate_unique_component_identity(
    _validator: Draft202012Validator,
    enabled: object,
    instance: object,
    schema: Mapping[str, Any],
) -> Iterator[ValidationError]:
    """Reject duplicate typed component identities even when metadata differs."""
    if enabled is not True or not isinstance(instance, list):
        return
    seen: dict[tuple[object, ...], int] = {}
    for index, item in enumerate(instance):
        if not isinstance(item, Mapping):
            continue
        identity = _component_identity(item)
        if identity is None:
            continue
        first_index = seen.setdefault(identity, index)
        if first_index == index:
            continue
        yield ValidationError(
            f"duplicate capability component identity at indexes {first_index} and {index}",
            validator=UNIQUE_COMPONENT_IDENTITY_KEYWORD,
            validator_value=enabled,
            instance=instance,
            schema=schema,
            path=deque((index,)),
        )


CatalogueContractValidator = validators.extend(
    Draft202012Validator,
    validators={
        UNIQUE_BY_KEYWORD: _validate_unique_by,
        MCP_TOOL_INVENTORY_KEYWORD: _validate_mcp_tool_inventory,
        UNIQUE_COMPONENT_IDENTITY_KEYWORD: _validate_unique_component_identity,
    },
    version="dex-lens-catalogue-v2",
)


def build_catalogue_schema_dialect() -> dict[str, object]:
    """Return the closed meta-schema for the required Lens vocabulary."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CATALOGUE_SCHEMA_DIALECT_ID,
        "$vocabulary": {
            "https://json-schema.org/draft/2020-12/vocab/core": True,
            "https://json-schema.org/draft/2020-12/vocab/applicator": True,
            "https://json-schema.org/draft/2020-12/vocab/unevaluated": True,
            "https://json-schema.org/draft/2020-12/vocab/validation": True,
            "https://json-schema.org/draft/2020-12/vocab/meta-data": True,
            "https://json-schema.org/draft/2020-12/vocab/format-annotation": True,
            "https://json-schema.org/draft/2020-12/vocab/content": True,
            UNIQUE_BY_VOCABULARY_ID: True,
            MCP_TOOL_INVENTORY_VOCABULARY_ID: True,
            UNIQUE_COMPONENT_IDENTITY_VOCABULARY_ID: True,
        },
        "$dynamicAnchor": "meta",
        "title": "Dex Lens catalogue v2 schema dialect",
        "allOf": [
            {"$ref": "https://json-schema.org/draft/2020-12/schema"},
        ],
        "type": ["object", "boolean"],
        "$comment": (
            "The required x-dex-lens-unique-by vocabulary rejects reused "
            "identifier fields inside arrays of otherwise different objects; "
            "the MCP inventory vocabulary enforces complete cross-field counts; "
            "component identities remain unique even when metadata differs."
        ),
        "properties": {
            UNIQUE_BY_KEYWORD: {
                "type": "string",
                "enum": ["job_id", "capability_id", "alias", "family_id"],
            },
            MCP_TOOL_INVENTORY_KEYWORD: {"type": "boolean"},
            UNIQUE_COMPONENT_IDENTITY_KEYWORD: {"type": "boolean"},
        },
    }


CatalogueContractValidator.META_SCHEMA = build_catalogue_schema_dialect()


def _close_entry_union(schema: dict[str, Any]) -> None:
    """Express the entry union as ``oneOf`` with five closed branches.

    pydantic emits the rollout-compatible union as an ``anyOf`` wrapping a
    discriminated ``oneOf``. The cross-repo contract states it more plainly:
    exactly one of five closed object shapes. Every branch forbids unknown
    fields and the class branches disagree on ``capability_class`` (the
    legacy branch forbids it entirely), so the branches are mutually
    exclusive and ``oneOf`` is exact, not merely stylistic.
    """
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise ValueError("catalogue schema has no $defs to build the entry union from")
    missing = [name for name in ENTRY_BRANCH_MODELS if name not in definitions]
    if missing:
        raise ValueError(f"catalogue schema is missing entry branch(es): {missing}")
    definitions["CatalogueCapabilityEntryV2"] = {
        "title": "CatalogueCapabilityEntryV2",
        "oneOf": [{"$ref": f"#/$defs/{name}"} for name in ENTRY_BRANCH_MODELS],
    }
    capabilities = definitions["CatalogueV2"]["properties"]["capabilities"]
    capabilities["items"] = {"$ref": "#/$defs/CatalogueCapabilityEntryV2"}


def build_catalogue_schema() -> dict[str, Any]:
    """Build the producer schema with its required dialect declared."""
    schema = SignedCatalogueEnvelopeV2.model_json_schema(
        ref_template="#/$defs/{model}",
        mode="validation",
    )
    _close_entry_union(schema)
    mcp_definition = schema["$defs"].get("McpServerCapabilityEntryV2")
    if not isinstance(mcp_definition, dict):
        raise ValueError("catalogue schema is missing MCP server entry definition")
    mcp_definition[MCP_TOOL_INVENTORY_KEYWORD] = True
    schema["$schema"] = CATALOGUE_SCHEMA_DIALECT_ID
    schema["$id"] = CATALOGUE_SCHEMA_ID
    schema[MINIMUM_VERSION_KEYWORD] = MINIMUM_LENS_VERSION
    schema[CONTRACT_STATUS_KEYWORD] = CONTRACT_STATUS
    schema["$comment"] = (
        "This contract requires the Dex Lens unique-by vocabulary. Vanilla "
        "Draft 2020-12 validation alone is incomplete; use the declared dialect "
        "and capability_exchange.catalogue.schema_contract.iter_catalogue_schema_errors."
    )
    schema["x-dex-lens-reference-validator"] = (
        "capability_exchange.catalogue.schema_contract.iter_catalogue_schema_errors"
    )
    return schema


def iter_catalogue_schema_errors(
    instance: object,
    *,
    schema: Mapping[str, Any] | None = None,
) -> Iterator[ValidationError]:
    """Yield complete structural and unique-identifier contract errors."""
    contract = dict(schema) if schema is not None else build_catalogue_schema()
    if contract.get("$schema") != CATALOGUE_SCHEMA_DIALECT_ID:
        yield ValidationError(
            "catalogue schema does not declare the required Dex Lens dialect",
            validator="$schema",
            validator_value=CATALOGUE_SCHEMA_DIALECT_ID,
            instance=instance,
            schema=contract,
        )
        return
    definitions = contract.get("$defs")
    catalogue_definition = (
        definitions.get("CatalogueV2") if isinstance(definitions, Mapping) else None
    )
    catalogue_properties = (
        catalogue_definition.get("properties")
        if isinstance(catalogue_definition, Mapping)
        else None
    )
    required_rules = {
        "jobs_taxonomy": "job_id",
        "capabilities": "capability_id",
        "capability_aliases": "alias",
        "capability_families": "family_id",
    }
    for collection, identifier in required_rules.items():
        collection_schema = (
            catalogue_properties.get(collection)
            if isinstance(catalogue_properties, Mapping)
            else None
        )
        if (
            not isinstance(collection_schema, Mapping)
            or collection_schema.get(UNIQUE_BY_KEYWORD) != identifier
        ):
            yield ValidationError(
                (
                    f"catalogue schema is missing required {UNIQUE_BY_KEYWORD} "
                    f"rule {collection!r} -> {identifier!r}"
                ),
                validator=UNIQUE_BY_KEYWORD,
                validator_value=identifier,
                instance=instance,
                schema=contract,
            )
            return
    mcp_definition = (
        definitions.get("McpServerCapabilityEntryV2")
        if isinstance(definitions, Mapping)
        else None
    )
    if (
        not isinstance(mcp_definition, Mapping)
        or mcp_definition.get(MCP_TOOL_INVENTORY_KEYWORD) is not True
    ):
        yield ValidationError(
            (
                f"catalogue schema is missing required {MCP_TOOL_INVENTORY_KEYWORD} "
                "rule on the MCP server entry"
            ),
            validator=MCP_TOOL_INVENTORY_KEYWORD,
            validator_value=True,
            instance=instance,
            schema=contract,
        )
        return
    family_definition = (
        definitions.get("CapabilityFamilyV2")
        if isinstance(definitions, Mapping)
        else None
    )
    family_properties = (
        family_definition.get("properties")
        if isinstance(family_definition, Mapping)
        else None
    )
    components_schema = (
        family_properties.get("components")
        if isinstance(family_properties, Mapping)
        else None
    )
    if (
        not isinstance(components_schema, Mapping)
        or components_schema.get(UNIQUE_COMPONENT_IDENTITY_KEYWORD) is not True
    ):
        yield ValidationError(
            (
                f"catalogue schema is missing required "
                f"{UNIQUE_COMPONENT_IDENTITY_KEYWORD} rule on family components"
            ),
            validator=UNIQUE_COMPONENT_IDENTITY_KEYWORD,
            validator_value=True,
            instance=instance,
            schema=contract,
        )
        return
    validator = CatalogueContractValidator(contract)
    yield from validator.iter_errors(instance)
