"""No aggregate score, maturity rank, or resemblance percentage is
representable in any diagnosis schema or report shape (#351; M2 criterion).

This is the schema test, not a code review: it walks every model field —
including nested models, through tuples, unions, and optionals — across the
whole diagnosis surface AND the jobs-first Capability Map (the M-D report
shape in :mod:`capability_exchange.capmap.model`) and proves that:

1. no field name could carry an aggregate (no score/rank/percentage/rating/
   grade/maturity/resemblance/aggregate/total-style name anywhere);
2. no field anywhere in the tree has a numeric type (int/float/complex) —
   the only quantities in the tree are timestamps and durations;
3. every model forbids extra fields, so an aggregate cannot be attached at
   runtime either;
4. the three axes are closed string vocabularies whose members contain no
   digits — an axis value cannot smuggle a number.
"""

from __future__ import annotations

import importlib
import typing
from datetime import datetime, timedelta
from enum import StrEnum

import pytest
from pydantic import BaseModel

import capability_exchange.capmap as capmap_package
import capability_exchange.diagnosis as diagnosis_package
from capability_exchange.capmap import CapabilityMap
from capability_exchange.diagnosis import CapabilityState, SafetyBoundary
from capability_exchange.evidence import EvidenceLevel

#: Field names that could express an aggregate, collapsed axis, or ranking.
FORBIDDEN_NAME_TOKENS = (
    "score",
    "rank",
    "rating",
    "grade",
    "percent",
    "maturity",
    "resemblance",
    "aggregate",
    "overall",
    "total",
    "average",
    "weight",
)

#: Numeric types that could carry an aggregate value.
NUMERIC_TYPES = (int, float, complex)

#: Non-numeric leaf quantities that are allowed (time, never a score).
ALLOWED_QUANTITY_TYPES = (datetime, timedelta)


def _nested_models(annotation: object) -> tuple[type[BaseModel], ...]:
    """Every pydantic model type reachable inside a type annotation."""
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            found.append(annotation)
        return tuple(found)
    for argument in typing.get_args(annotation):
        found.extend(_nested_models(argument))
    return tuple(found)


def _contains_numeric(annotation: object) -> bool:
    """Whether a type annotation admits an int/float/complex value anywhere."""
    if isinstance(annotation, type):
        # bool is a subclass of int but carries one bit, not a quantity.
        if annotation is bool:
            return False
        if issubclass(annotation, StrEnum):
            return False
        if annotation in ALLOWED_QUANTITY_TYPES:
            return False
        return issubclass(annotation, NUMERIC_TYPES)
    return any(_contains_numeric(argument) for argument in typing.get_args(annotation))


def walk_model_fields(
    model: type[BaseModel], seen: set[type[BaseModel]] | None = None
) -> dict[str, object]:
    """Every ``Model.field`` → annotation pair reachable from ``model``."""
    seen = seen if seen is not None else set()
    if model in seen:
        return {}
    seen.add(model)
    fields: dict[str, object] = {}
    for name, info in model.model_fields.items():
        fields[f"{model.__name__}.{name}"] = info.annotation
        for nested in _nested_models(info.annotation):
            fields.update(walk_model_fields(nested, seen))
    return fields


#: The complete diagnosis report surface: the map is the report shape, and
#: walking it reaches JobFindings, Finding, and every nested model.
ALL_FIELDS = walk_model_fields(CapabilityMap)


class TestAggregateIsUnrepresentable:
    def test_the_walk_reaches_the_whole_tree(self) -> None:
        walked_models = {key.split(".")[0] for key in ALL_FIELDS}
        assert {
            "CapabilityMap",
            "JobFindings",
            "Finding",
            "EvidenceItem",
            "SuccessContract",
            "JobBoundaries",
        } <= walked_models

    @pytest.mark.parametrize("field_key", sorted(ALL_FIELDS))
    def test_no_field_name_could_carry_an_aggregate(self, field_key: str) -> None:
        field_name = field_key.split(".", 1)[1].lower()
        for token in FORBIDDEN_NAME_TOKENS:
            assert token not in field_name, (
                f"{field_key} could carry an aggregate ({token!r}); the three "
                f"axes must never be collapsed (#351)"
            )

    @pytest.mark.parametrize("field_key", sorted(ALL_FIELDS))
    def test_no_field_anywhere_has_a_numeric_type(self, field_key: str) -> None:
        assert not _contains_numeric(ALL_FIELDS[field_key]), (
            f"{field_key} admits a numeric value; a number field is where an "
            f"aggregate would live, so none exists in any diagnosis schema"
        )

    def test_every_model_in_the_tree_forbids_extra_fields(self) -> None:
        checked: set[type[BaseModel]] = set()
        walk_model_fields(CapabilityMap, checked)
        assert checked
        for model in checked:
            assert model.model_config.get("extra") == "forbid", (
                f"{model.__name__} would accept an attached aggregate at runtime"
            )

    def test_every_diagnosis_and_capmap_model_is_covered_by_this_walk(self) -> None:
        """No diagnosis or Capability Map model exists outside the walked
        report tree — the map is the report shape, and nothing escapes it."""
        package_models: set[type[BaseModel]] = set()
        for module_name in (
            "diagnosis.finding",
            "diagnosis.engine",
            "diagnosis.foundations",
            "capmap.model",
            "capmap.render",
            "capmap.correct",
        ):
            module = importlib.import_module(f"capability_exchange.{module_name}")
            for value in vars(module).values():
                if (
                    isinstance(value, type)
                    and issubclass(value, BaseModel)
                    and value.__module__.startswith(
                        ("capability_exchange.diagnosis", "capability_exchange.capmap")
                    )
                ):
                    package_models.add(value)
        assert package_models  # the walk below must have something to cover
        walked: set[type[BaseModel]] = set()
        walk_model_fields(CapabilityMap, walked)
        assert package_models <= walked

    def test_axis_vocabularies_contain_no_digits(self) -> None:
        for axis_enum in (CapabilityState, EvidenceLevel, SafetyBoundary):
            for member in axis_enum:
                assert not any(char.isdigit() for char in member.value)

    def test_packages_export_no_aggregate_named_symbol(self) -> None:
        for package in (diagnosis_package, capmap_package):
            for symbol in package.__all__:
                lowered = symbol.lower()
                for token in FORBIDDEN_NAME_TOKENS:
                    assert token not in lowered
