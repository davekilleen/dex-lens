"""G2 field-level data boundary (module M-B slice).

Everything the product persists or transmits crosses this boundary:

- :mod:`capability_exchange.boundary.inventory` — the machine-readable data
  inventory (``data_inventory.yaml``), schema-validated at import and in CI.
- :mod:`capability_exchange.boundary.serialization` — the typed serialization
  boundary: only inventoried fields are serializable; an uninventoried field
  raises at any serialization attempt. Default processing is ephemeral.
- :mod:`capability_exchange.boundary.deletion` — the deletion-path registry:
  every stored field maps to a deletion function that verifiably removes bytes.
- :mod:`capability_exchange.boundary.crashlog` — crash-log formatting that
  never includes private field values.

This package sits on the diagnosis side and holds no mutating entry point
toward any inspected system; the only writes it performs are the product's
own local crash logs, and those are inventoried and deletable.
"""

from capability_exchange.boundary.inventory import (
    FieldEntry,
    Inventory,
    InventoryError,
    StorageDeclaration,
    active_inventory,
)
from capability_exchange.boundary.serialization import (
    EphemeralByDefaultError,
    InventoriedModel,
    NoTransmissibleFieldsError,
    UninventoriedFieldError,
)

__all__ = [
    "EphemeralByDefaultError",
    "FieldEntry",
    "Inventory",
    "InventoriedModel",
    "InventoryError",
    "NoTransmissibleFieldsError",
    "StorageDeclaration",
    "UninventoriedFieldError",
    "active_inventory",
]
