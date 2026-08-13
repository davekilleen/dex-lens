"""Export the cross-repo Dex Lens catalogue JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from capability_exchange.catalogue.schema_contract import (
    build_catalogue_schema,
    build_catalogue_schema_dialect,
)

SCHEMA_PATH = Path("schemas/dex-lens-catalogue-v2.schema.json")
DIALECT_PATH = Path("schemas/dex-lens-catalogue-v2-dialect.schema.json")


def main() -> None:
    artifacts = {
        SCHEMA_PATH: build_catalogue_schema(),
        DIALECT_PATH: build_catalogue_schema_dialect(),
    }
    for path, document in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
