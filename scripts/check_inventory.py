#!/usr/bin/env python3
"""g2-inventory-check: CI enforcement of the field-level data boundary.

Walks every module in the ``capability_exchange`` package and fails the build
if the G2 contract is broken anywhere:

1. the packaged ``data_inventory.yaml`` must parse and schema-validate
   (already enforced at import — an invalid inventory fails here too);
2. every field of every :class:`InventoriedModel` subclass, plus explicitly
   retained local snapshot provenance, must have an inventory entry;
3. every inventory entry must correspond to an existing governed field — the
   inventory may not drift ahead of or behind the code;
4. every pydantic model in the package must be an ``InventoriedModel`` or an
   explicitly allowlisted internal schema (currently only the inventory's
   own metadata models, which describe the inventory rather than carry
   product data) — so no serializable model can bypass the boundary;
5. every storage-declaring entry must map to a registered deletion function.

Exit status 0 means the boundary holds; anything else fails the build.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Internal schema models that describe the inventory itself and are never
# persisted or transmitted as product data. Additions here are a reviewed
# G2 decision, not a convenience.
ALLOWED_PLAIN_MODELS = {
    "capability_exchange.boundary.inventory.StorageDeclaration",
    "capability_exchange.boundary.inventory.FieldEntry",
    "capability_exchange.boundary.inventory.Inventory",
}

# Browser/session state is a first-class G2 surface. Keeping the required
# model name here makes removal or replacement of that declaration a CI
# failure instead of allowing a dataclass field to become an untracked cache.
REQUIRED_CONCIERGE_MODELS = {"ConciergeSessionState"}

PACKAGE = "capability_exchange"


def _import_all_package_modules() -> list[str]:
    package = importlib.import_module(PACKAGE)
    imported = [PACKAGE]
    for info in pkgutil.walk_packages(package.__path__, prefix=f"{PACKAGE}."):
        importlib.import_module(info.name)
        imported.append(info.name)
    return imported


def _package_model_classes() -> list[type]:
    """Every pydantic model class defined in package modules now loaded."""
    from pydantic import BaseModel

    classes: list[type] = []
    seen: set[int] = set()
    for module_name, module in list(sys.modules.items()):
        if module is None or not module_name.startswith(PACKAGE):
            continue
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseModel)
                and value is not BaseModel
                and value.__module__ == module_name
                and id(value) not in seen
            ):
                classes.append(value)
                seen.add(id(value))
    return classes


def collect_problems() -> list[str]:
    """Return every G2 boundary violation found in the package. Empty = green."""
    from capability_exchange.boundary.deletion import verify_deletion_coverage
    from capability_exchange.boundary.inventory import active_inventory
    from capability_exchange.boundary.serialization import InventoriedModel

    _import_all_package_modules()
    inventory = active_inventory()
    problems: list[str] = []

    # These records are deliberately not serializable models: they retain
    # local-only snapshot provenance in process memory. Their fields still
    # cross the collection boundary, so the checker inventories them
    # explicitly instead of letting "not persisted" mean "not governed".
    from capability_exchange.adapters.claude_code.snapshot import (
        ApprovedSnapshotSource,
        InspectionSnapshot,
        SnapshotEntry,
    )

    local_snapshot_fields = {
        ApprovedSnapshotSource: frozenset({"source_id", "source_class", "scope_reference"}),
        InspectionSnapshot: frozenset({"approved_sources"}),
        SnapshotEntry: frozenset({"source"}),
    }
    required_local_keys: set[str] = set()
    for cls, field_names in local_snapshot_fields.items():
        annotations = getattr(cls, "__annotations__", {})
        for field_name in field_names:
            key = f"{cls.__name__}.{field_name}"
            required_local_keys.add(key)
            if field_name not in annotations and not isinstance(
                getattr(cls, field_name, None), property
            ):
                problems.append(
                    f"required local inventory declaration {key}: field no longer exists"
                )
                continue
            entry = inventory.fields.get(key)
            if entry is None:
                problems.append(
                    f"{key}: retained local snapshot provenance has no data-inventory entry"
                )
            elif entry.storage is not None or entry.sharing != "never":
                problems.append(
                    f"{key}: local snapshot provenance must remain ephemeral and unshared"
                )

    inventoried_models: dict[str, type] = {}
    for cls in _package_model_classes():
        qualified = f"{cls.__module__}.{cls.__name__}"
        if issubclass(cls, InventoriedModel):
            if cls is not InventoriedModel:
                # The inventory namespace is keyed by bare class name, so it
                # must actually be unique: a second model reusing a name would
                # silently inherit the first model's entries and serialize
                # fields that were never inventoried. Collision is a build
                # failure, not a shadowing.
                clash = inventoried_models.get(cls.__name__)
                if clash is not None:
                    problems.append(
                        f"{qualified}: inventory namespace collision with "
                        f"{clash.__module__}.{clash.__name__} — the data "
                        f"inventory is keyed by bare class name, so two models "
                        f"named {cls.__name__!r} would share entries and one "
                        f"could serialize uninventoried fields. Rename one."
                    )
                    continue
                inventoried_models[cls.__name__] = cls
        elif qualified not in ALLOWED_PLAIN_MODELS:
            problems.append(
                f"{qualified}: pydantic model does not subclass InventoriedModel; "
                f"models outside the typed serialization boundary may not exist in "
                f"this package (allowlisting is a reviewed G2 decision)"
            )

    for model_name in sorted(REQUIRED_CONCIERGE_MODELS):
        if model_name not in inventoried_models:
            problems.append(
                f"{model_name}: required concierge/session state model is not "
                "inside the InventoriedModel boundary"
            )

    # Every model field needs an inventory entry (uninventoried => build fails).
    for model_name, cls in sorted(inventoried_models.items()):
        for field_name in cls.model_fields:
            key = f"{model_name}.{field_name}"
            if key not in inventory.fields:
                problems.append(
                    f"{cls.__module__}.{key}: persisted/transmitted field has no "
                    f"data-inventory entry in data_inventory.yaml"
                )

    # Every inventory entry needs a matching model field (no drift).
    for key in sorted(inventory.fields):
        model_name, _, field_name = key.partition(".")
        cls = inventoried_models.get(model_name)
        if key in required_local_keys:
            continue
        if cls is None:
            problems.append(
                f"inventory entry {key}: no InventoriedModel named {model_name!r} "
                f"exists in the package"
            )
        elif field_name not in cls.model_fields:
            problems.append(
                f"inventory entry {key}: model {model_name} has no field {field_name!r}"
            )

    # Every stored field's deletion path must be registered.
    problems.extend(verify_deletion_coverage(inventory))

    return problems


def main() -> int:
    try:
        problems = collect_problems()
    except Exception as exc:  # noqa: BLE001 - any failure here fails the build
        print(f"g2-inventory-check: FAILED to run: {type(exc).__name__}: {exc}")
        return 1
    if problems:
        print(f"g2-inventory-check: {len(problems)} violation(s) of the G2 data boundary:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    from capability_exchange.boundary.inventory import active_inventory

    inventory = active_inventory()
    stored = sum(1 for entry in inventory.fields.values() if entry.stores)
    transmitted = sum(1 for entry in inventory.fields.values() if entry.shares)
    print(
        f"g2-inventory-check: OK — {len(inventory.fields)} inventoried field(s), "
        f"{stored} stored (all with registered deletion paths), "
        f"{transmitted} transmitted through closed reviewed paths."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
