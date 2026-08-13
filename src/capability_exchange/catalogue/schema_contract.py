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
    SignedCatalogueEnvelopeV2,
)

CATALOGUE_SCHEMA_ID = "https://heydex.ai/catalogue/dex-lens/v2.schema.json"
CATALOGUE_SCHEMA_DIALECT_ID = (
    "https://heydex.ai/catalogue/dex-lens/v2-dialect.schema.json"
)
UNIQUE_BY_VOCABULARY_ID = (
    "https://heydex.ai/catalogue/dex-lens/vocab/unique-by"
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


CatalogueContractValidator = validators.extend(
    Draft202012Validator,
    validators={UNIQUE_BY_KEYWORD: _validate_unique_by},
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
        },
        "$dynamicAnchor": "meta",
        "title": "Dex Lens catalogue v2 schema dialect",
        "allOf": [
            {"$ref": "https://json-schema.org/draft/2020-12/schema"},
        ],
        "type": ["object", "boolean"],
        "$comment": (
            "The required x-dex-lens-unique-by vocabulary rejects reused "
            "identifier fields inside arrays of otherwise different objects."
        ),
        "properties": {
            UNIQUE_BY_KEYWORD: {
                "type": "string",
                "enum": ["job_id", "capability_id"],
            }
        },
    }


CatalogueContractValidator.META_SCHEMA = build_catalogue_schema_dialect()


def build_catalogue_schema() -> dict[str, Any]:
    """Build the producer schema with its required dialect declared."""
    schema = SignedCatalogueEnvelopeV2.model_json_schema(
        ref_template="#/$defs/{model}",
        mode="validation",
    )
    schema["$schema"] = CATALOGUE_SCHEMA_DIALECT_ID
    schema["$id"] = CATALOGUE_SCHEMA_ID
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
    validator = CatalogueContractValidator(contract)
    yield from validator.iter_errors(instance)
