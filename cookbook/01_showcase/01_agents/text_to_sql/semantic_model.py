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
"""

import json

# ============================================================================
# Semantic Model Definition
# ============================================================================
# The semantic model helps the agent identify the tables and columns to search
# for during query construction. This is sent in the system prompt, the agent
# then uses the `search_knowledge_base` tool to get table metadata, rules,
# and sample queries.

SEMANTIC_MODEL = {
    "tables": [
        {
            "table_name": "constructors_championship",
            "table_description": "Constructor championship standings (1958 to 2020).",
            "use_cases": [
                "Constructor standings by year",
                "Team performance over time",
            ],
        },
        {
            "table_name": "drivers_championship",
            "table_description": "Driver championship standings (1950 to 2020).",
            "use_cases": [
                "Driver standings by year",
                "Comparing driver points across seasons",
            ],
        },
        {
            "table_name": "fastest_laps",
            "table_description": "Fastest lap records per race (1950 to 2020).",
            "use_cases": [
                "Fastest laps by driver or team",
                "Fastest lap trends over time",
            ],
        },
        {
            "table_name": "race_results",
            "table_description": "Per-race results including positions, drivers, teams, points (1950 to 2020).",
            "use_cases": [
                "Driver career results",
                "Finish position distributions",
                "Points by season",
            ],
        },
        {
            "table_name": "race_wins",
            "table_description": "Race winners and venue info (1950 to 2020).",
            "use_cases": [
                "Win counts by driver/team",
                "Wins by circuit or country",
            ],
        },
    ],
}

# Serialized version for embedding in system prompts
SEMANTIC_MODEL_STR = json.dumps(SEMANTIC_MODEL, indent=2)
