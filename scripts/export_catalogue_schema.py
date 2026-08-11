"""Export the cross-repo Dex Lens catalogue JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from capability_exchange.catalogue.v2 import SignedCatalogueEnvelopeV2

SCHEMA_PATH = Path("schemas/dex-lens-catalogue-v2.schema.json")


def main() -> None:
    schema = SignedCatalogueEnvelopeV2.model_json_schema(
        ref_template="#/$defs/{model}",
        mode="validation",
    )
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://heydex.ai/catalogue/dex-lens/v2.schema.json"
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
