"""G2 typed serialization boundary.

:class:`InventoriedModel` is the base class for every model whose values may
ever be persisted or transmitted. The guard is structural, not advisory:

- Any model field without an entry in the active data inventory raises
  :class:`UninventoriedFieldError` at serialization attempt — including when
  the model is nested inside another model's payload. An uninventoried field
  is private, non-persistable, non-transmittable by construction.
- Default processing is ephemeral: :meth:`InventoriedModel.dump_for_storage`
  emits only fields whose inventory entry declares storage, and refuses
  (rather than writing an empty payload) when nothing is declared stored.
- :meth:`InventoriedModel.dump_for_transmission` emits only fields whose
  entry declares sharing. At M1 the inventory schema admits no sharing at
  all, so every transmission attempt refuses: diagnosis is telemetry-free.

Error messages name the offending field but never echo its value.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer

from capability_exchange.boundary.inventory import FieldEntry, Inventory, active_inventory


class BoundaryError(Exception):
    """Base class for serialization-boundary refusals."""


class UninventoriedFieldError(BoundaryError):
    """A model field has no data-inventory entry: it must not be serialized."""

    def __init__(self, model_name: str, field_name: str) -> None:
        self.inventory_key = f"{model_name}.{field_name}"
        super().__init__(
            f"refusing to serialize {self.inventory_key}: no data-inventory entry. "
            f"Uninventoried fields are private — non-persistable and "
            f"non-transmittable. Add a complete entry to data_inventory.yaml "
            f"(collection, derivation, display, storage, sharing, deletion, audit) "
            f"or remove the field."
        )


class EphemeralByDefaultError(BoundaryError):
    """No field of this model declares storage: there is nothing to persist."""


class NoTransmissibleFieldsError(BoundaryError):
    """No field of this model declares sharing: there is nothing to transmit."""


def _walk_for_precheck(value: Any, inventory: Inventory, seen: set[int]) -> None:
    """Recursively pre-check nested InventoriedModel instances in a value."""
    if isinstance(value, InventoriedModel):
        if id(value) in seen:
            return
        seen.add(id(value))
        value._precheck_tree(inventory, seen)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            _walk_for_precheck(item, inventory, seen)
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk_for_precheck(key, inventory, seen)
            _walk_for_precheck(item, inventory, seen)


class InventoriedModel(BaseModel):
    """Base class for models crossing the G2 boundary.

    Subclasses gain nothing implicitly: every field must still earn its
    inventory entry before any serialization succeeds.
    """

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def _inventory_key(cls, field_name: str) -> str:
        return f"{cls.__name__}.{field_name}"

    @classmethod
    def _assert_fully_inventoried(cls, inventory: Inventory) -> dict[str, FieldEntry]:
        """Return this model's entries, or raise on the first missing one."""
        entries: dict[str, FieldEntry] = {}
        for field_name in cls.model_fields:
            entry = inventory.fields.get(cls._inventory_key(field_name))
            if entry is None:
                raise UninventoriedFieldError(cls.__name__, field_name)
            entries[field_name] = entry
        return entries

    def _precheck_tree(self, inventory: Inventory, seen: set[int]) -> None:
        """Assert this model and every nested InventoriedModel is inventoried."""
        type(self)._assert_fully_inventoried(inventory)
        for field_name in type(self).model_fields:
            _walk_for_precheck(getattr(self, field_name), inventory, seen)

    @model_serializer(mode="wrap")
    def _guarded_serialize(self, handler: SerializerFunctionWrapHandler) -> Any:
        # Last-ditch guard on every pydantic serialization route (including
        # ones that bypass the overrides below, e.g. a plain BaseModel parent
        # or a TypeAdapter). pydantic wraps errors raised here in
        # PydanticSerializationError — still a refusal, so still fail closed;
        # the overrides below exist to surface the typed error directly.
        type(self)._assert_fully_inventoried(active_inventory())
        return handler(self)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        self._precheck_tree(active_inventory(), seen=set())
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        self._precheck_tree(active_inventory(), seen=set())
        return super().model_dump_json(**kwargs)

    def dump_for_storage(self) -> dict[str, Any]:
        """Payload for persistence: only storage-declared fields, or refuse.

        Raises :class:`UninventoriedFieldError` if any field lacks an entry
        and :class:`EphemeralByDefaultError` if no field declares storage —
        nothing persists unless the inventory says so.
        """
        entries = type(self)._assert_fully_inventoried(active_inventory())
        stored_fields = [name for name, entry in entries.items() if entry.stores]
        if not stored_fields:
            raise EphemeralByDefaultError(
                f"{type(self).__name__} has no storage-declared fields; "
                f"default processing is ephemeral and nothing may be persisted."
            )
        payload = self.model_dump(mode="json")
        return {name: payload[name] for name in stored_fields}

    def dump_for_transmission(self) -> dict[str, Any]:
        """Payload for transmission: only sharing-declared fields, or refuse.

        At M1 the inventory schema admits ``sharing: never`` only, so this
        always refuses — diagnosis transmits nothing.
        """
        entries = type(self)._assert_fully_inventoried(active_inventory())
        shared_fields = [name for name, entry in entries.items() if entry.shares]
        if not shared_fields:
            raise NoTransmissibleFieldsError(
                f"{type(self).__name__} has no sharing-declared fields; "
                f"nothing may leave the machine."
            )
        payload = self.model_dump(mode="json")
        return {name: payload[name] for name in shared_fields}
