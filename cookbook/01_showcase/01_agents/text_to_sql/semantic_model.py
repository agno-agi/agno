"""
Semantic Model
==============

Builds schema metadata from knowledge/*.json files for the Text-to-SQL agent.
"""

import json
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def build_semantic_model() -> dict:
    """Build semantic model from knowledge JSON files."""
    tables = []
    for f in sorted(KNOWLEDGE_DIR.glob("*.json")):
        with open(f) as fp:
            table = json.load(fp)
            tables.append(
                {
                    "table_name": table["table_name"],
                    "table_description": table["table_description"],
                    "use_cases": table.get("use_cases", []),
                    "data_quality_notes": table.get("data_quality_notes", []),
                }
            )
    return {"tables": tables}


SEMANTIC_MODEL = build_semantic_model()
SEMANTIC_MODEL_STR = json.dumps(SEMANTIC_MODEL, indent=2)
