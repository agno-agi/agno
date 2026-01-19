"""
Semantic Model for Text-to-SQL Agent
=====================================

Defines the schema metadata for F1 data tables. The semantic model provides
high-level descriptions of available tables and their use cases, helping
the agent identify which tables to query for different types of questions.

The agent uses this model to:
1. Understand what data is available
2. Identify relevant tables for a query
3. Generate appropriate SQL based on table purposes

The semantic model is built dynamically from the knowledge/*.json files,
ensuring a single source of truth for table metadata.
"""

import json
from pathlib import Path

# ============================================================================
# Semantic Model Builder
# ============================================================================
# Builds the semantic model from knowledge JSON files to maintain a single
# source of truth. Each JSON file contains table_name, table_description,
# use_cases, and data_quality_notes.


def build_semantic_model() -> dict:
    """Build semantic model from knowledge JSON files.

    Reads all .json files in the knowledge/ directory and extracts
    table metadata for the semantic model.

    Returns:
        dict: Semantic model with tables list containing name, description,
              use_cases, and data_quality_notes for each table.
    """
    knowledge_dir = Path(__file__).parent / "knowledge"

    # Fallback if knowledge directory doesn't exist yet
    if not knowledge_dir.exists():
        return {"tables": _get_fallback_tables()}

    tables = []
    for f in sorted(knowledge_dir.glob("*.json")):
        try:
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
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Failed to load {f.name}: {e}")
            continue

    # Use fallback if no tables loaded
    if not tables:
        return {"tables": _get_fallback_tables()}

    return {"tables": tables}


def _get_fallback_tables() -> list:
    """Fallback table definitions if knowledge files are not available.

    Returns:
        list: Basic table metadata for F1 dataset.
    """
    return [
        {
            "table_name": "constructors_championship",
            "table_description": "Constructor championship standings (1958 to 2020).",
            "use_cases": [
                "Constructor standings by year",
                "Team performance over time",
            ],
            "data_quality_notes": [
                "position is INTEGER type - compare with numbers (position = 1)"
            ],
        },
        {
            "table_name": "drivers_championship",
            "table_description": "Driver championship standings (1950 to 2020).",
            "use_cases": [
                "Driver standings by year",
                "Comparing driver points across seasons",
            ],
            "data_quality_notes": [
                "position is TEXT type - compare with strings (position = '1')"
            ],
        },
        {
            "table_name": "fastest_laps",
            "table_description": "Fastest lap records per race (1950 to 2020).",
            "use_cases": [
                "Fastest laps by driver or team",
                "Fastest lap trends over time",
            ],
            "data_quality_notes": ["Uses driver_tag column (not name_tag)"],
        },
        {
            "table_name": "race_results",
            "table_description": "Per-race results including positions, drivers, teams, points (1950 to 2020).",
            "use_cases": [
                "Driver career results",
                "Finish position distributions",
                "Points by season",
            ],
            "data_quality_notes": [
                "position is TEXT - may contain 'Ret', 'DSQ', 'DNS', 'NC'"
            ],
        },
        {
            "table_name": "race_wins",
            "table_description": "Race winners and venue info (1950 to 2020).",
            "use_cases": [
                "Win counts by driver/team",
                "Wins by circuit or country",
            ],
            "data_quality_notes": [
                "date is TEXT format 'DD Mon YYYY' - use TO_DATE() to parse"
            ],
        },
    ]


# ============================================================================
# Semantic Model Export
# ============================================================================
# Build the model once at import time
SEMANTIC_MODEL = build_semantic_model()

# Serialized version for embedding in system prompts
SEMANTIC_MODEL_STR = json.dumps(SEMANTIC_MODEL, indent=2)

# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "SEMANTIC_MODEL",
    "SEMANTIC_MODEL_STR",
    "build_semantic_model",
]
