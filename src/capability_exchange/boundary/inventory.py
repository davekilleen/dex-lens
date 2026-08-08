"""G2 machine-readable data inventory, schema-validated at import and in CI.

The inventory (``data_inventory.yaml``) covers every field the product
persists or transmits. Each entry declares collection, derivation, display,
storage, sharing, deletion, and audit. The typed serialization boundary
(:mod:`capability_exchange.boundary.serialization`) refuses to serialize any
model field without an entry here — uninventoried fields are private,
non-persistable, and non-transmittable by construction.

The inventory file is parsed by a deliberately strict YAML-subset parser
(2-space indentation, ``key: value`` scalars, nested mappings, comments;
no flow syntax, no anchors, no tabs, no lists). The product may not add a
YAML dependency for this file, and the narrow grammar fails closed: anything
outside the subset raises :class:`InventoryError` rather than being guessed
at. Schema validation itself is pydantic.

M1 posture: ``sharing`` only admits ``never``. Diagnosis is telemetry-free
and ephemeral by default; the first approved network flow (catalog refresh,
HANDOFF D8) requires widening this schema, which reopens G2 review.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class InventoryError(Exception):
    """The data inventory failed to parse or validate. Fail closed."""


# --------------------------------------------------------------------------
# Schema (pydantic; the source of truth for what an entry must declare)
# --------------------------------------------------------------------------

_FIELD_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_DELETION_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")

#: Sentinel deletion value for fields that are never stored.
NOT_STORED = "not-stored"


class StorageDeclaration(BaseModel):
    """Where and for how long a stored field's bytes live."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location: str = Field(min_length=1)
    duration: str = Field(min_length=1)


class FieldEntry(BaseModel):
    """One inventoried field: the complete G2 declaration set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1)
    collection: str = Field(min_length=1)
    derivation: str = Field(min_length=1)
    display: str = Field(min_length=1)
    storage: StorageDeclaration | None
    sharing: Literal["never"]
    deletion: str = Field(min_length=1)
    audit: str = Field(min_length=1)

    @field_validator("storage", mode="before")
    @classmethod
    def _none_scalar_means_ephemeral(cls, value: object) -> object:
        if value == "none":
            return None
        return value

    @model_validator(mode="after")
    def _storage_and_deletion_agree(self) -> FieldEntry:
        if self.storage is None:
            if self.deletion != NOT_STORED:
                raise ValueError(
                    f"ephemeral field names deletion path {self.deletion!r}; "
                    f"an unstored field must declare deletion: {NOT_STORED}"
                )
        else:
            if self.deletion == NOT_STORED:
                raise ValueError(
                    "field declares storage but no deletion path; "
                    "every stored field must map to a registered deletion path"
                )
            if not _DELETION_ID_RE.match(self.deletion):
                raise ValueError(f"deletion path id {self.deletion!r} is not kebab-case")
        return self

    @property
    def stores(self) -> bool:
        return self.storage is not None

    @property
    def shares(self) -> bool:
        return self.sharing != "never"


class Inventory(BaseModel):
    """The whole inventory: version plus one entry per inventoried field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_version: int
    fields: dict[str, FieldEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _keys_name_model_and_field(self) -> Inventory:
        for key in self.fields:
            if not _FIELD_KEY_RE.match(key):
                raise ValueError(
                    f"inventory key {key!r} must be '<ModelName>.<field_name>'"
                )
        return self


# --------------------------------------------------------------------------
# Strict YAML-subset parser (fail closed on anything outside the subset)
# --------------------------------------------------------------------------

_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\-]*):(?:[ ]+(\S.*))?$")
_FORBIDDEN_BARE_PREFIXES = tuple("[{'&*!|>%@`\"")


@dataclass(frozen=True)
class _Token:
    lineno: int
    indent: int
    key: str
    value: str | None  # None => nested mapping follows


def _err(lineno: int, message: str) -> InventoryError:
    return InventoryError(f"data inventory line {lineno}: {message}")


def _parse_scalar(raw: str, lineno: int) -> str:
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"'):
            raise _err(lineno, "unterminated quoted string")
        inner = raw[1:-1]
        if '"' in inner or "\\" in inner:
            raise _err(lineno, "escapes and embedded quotes are outside the subset")
        return inner
    if raw[0] in _FORBIDDEN_BARE_PREFIXES:
        raise _err(lineno, f"flow/complex YAML syntax {raw[0]!r} is outside the subset")
    if " #" in raw:
        raise _err(lineno, "inline comments are outside the subset")
    return raw


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        leading = line[: len(line) - len(line.lstrip())]
        if "\t" in leading:
            raise _err(lineno, "tab in indentation")
        indent = len(leading)
        if indent % 2 != 0:
            raise _err(lineno, "indentation must be a multiple of 2 spaces")
        match = _LINE_RE.match(line.strip())
        if not match:
            raise _err(lineno, f"unparseable line {line.strip()!r}")
        key, value = match.group(1), match.group(2)
        tokens.append(
            _Token(
                lineno=lineno,
                indent=indent,
                key=key,
                value=None if value is None else _parse_scalar(value, lineno),
            )
        )
    return tokens


def _parse_block(tokens: list[_Token], start: int, indent: int) -> tuple[dict[str, object], int]:
    mapping: dict[str, object] = {}
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token.indent < indent:
            break
        if token.indent > indent:
            raise _err(token.lineno, "unexpected indentation")
        if token.key in mapping:
            raise _err(token.lineno, f"duplicate key {token.key!r}")
        if token.value is None:
            child, i = _parse_block(tokens, i + 1, indent + 2)
            if not child:
                raise _err(token.lineno, f"key {token.key!r} opens an empty mapping")
            mapping[token.key] = child
        else:
            mapping[token.key] = token.value
            i += 1
    return mapping, i


def parse_yaml_subset(text: str) -> dict[str, object]:
    """Parse the strict inventory YAML subset; raise :class:`InventoryError` otherwise."""
    tokens = _tokenize(text)
    mapping, consumed = _parse_block(tokens, 0, 0)
    if consumed != len(tokens):
        raise _err(tokens[consumed].lineno, "indentation does not return to a parent level")
    return mapping


# --------------------------------------------------------------------------
# Loading and the active inventory
# --------------------------------------------------------------------------

_PACKAGED_INVENTORY_PATH = Path(__file__).resolve().parent / "data_inventory.yaml"


def load_inventory_text(text: str) -> Inventory:
    """Parse and schema-validate an inventory document. Fail closed."""
    parsed = parse_yaml_subset(text)
    try:
        return Inventory.model_validate(parsed)
    except ValidationError as exc:
        raise InventoryError(f"data inventory failed schema validation:\n{exc}") from exc


@lru_cache(maxsize=1)
def load_packaged_inventory() -> Inventory:
    """Load and validate the packaged ``data_inventory.yaml``.

    The file ships inside the package directory and is declared in
    ``[tool.setuptools.package-data]``, so a built wheel contains it —
    ``tests/test_packaging.py`` builds a real wheel and asserts exactly that.
    That test exists because an editable install (the M1 layout, and what CI
    uses) reads this straight from the source tree and would hide its absence
    from the artifact people actually install.
    """
    try:
        text = _PACKAGED_INVENTORY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise InventoryError(
            f"packaged data inventory missing at {_PACKAGED_INVENTORY_PATH}: {exc}"
        ) from exc
    return load_inventory_text(text)


# Validate at import: an invalid packaged inventory is an import error, so no
# code path can serialize anything before the inventory is known-good.
_ACTIVE: Inventory = load_packaged_inventory()


def active_inventory() -> Inventory:
    """The inventory the serialization boundary consults."""
    return _ACTIVE


@contextmanager
def use_inventory(substitute: Inventory) -> Iterator[Inventory]:
    """Temporarily swap the active inventory (tests only).

    The packaged inventory is restored on exit even if the body raises. This
    exists so hostile-fixture tests can probe the boundary; product code must
    never call it.
    """
    global _ACTIVE
    previous = _ACTIVE
    _ACTIVE = substitute
    try:
        yield substitute
    finally:
        _ACTIVE = previous
