"""
Save Validated Query Tool
=========================

Custom tool for saving validated SQL queries to the knowledge base.
Uses a module-level variable to avoid circular import issues.

This tool enables the self-learning loop:
1. Agent generates and executes a query
2. User validates the results
3. Agent saves the query with metadata for future retrieval
4. Future similar questions benefit from the saved pattern
"""

import json
from typing import TYPE_CHECKING, Optional

from agno.knowledge.reader.text_reader import TextReader
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.knowledge.knowledge import Knowledge

# ============================================================================
# Module-level Knowledge Reference
# ============================================================================
# Set by agent.py after initialization to avoid circular imports
_sql_agent_knowledge: Optional["Knowledge"] = None


def set_knowledge(knowledge: "Knowledge") -> None:
    """Set the knowledge base reference for the save tool.

    Called by agent.py after creating the knowledge instance.
    """
    global _sql_agent_knowledge
    _sql_agent_knowledge = knowledge


# ============================================================================
# Save Validated Query Tool
# ============================================================================
def save_validated_query(
    name: str,
    question: str,
    query: str,
    summary: Optional[str] = None,
    notes: Optional[str] = None,
    data_quality_notes: Optional[str] = None,
) -> str:
    """Save a validated SQL query and its explanation to the knowledge base.

    Call this tool ONLY after:
    1. The query has been executed successfully
    2. The user has confirmed the results are correct
    3. The user has agreed to save the query

    Args:
        name: Short descriptive name for the query (e.g., "championship_wins_by_driver").
        question: The original natural language question from the user.
        query: The exact SQL query that was executed and validated.
        summary: Brief explanation of what the query does and what it returns.
        notes: Any caveats, assumptions, or limitations of the query.
        data_quality_notes: Any data quality issues encountered and how they were handled
            (e.g., "position is TEXT in drivers_championship - used string comparison").

    Returns:
        str: Status message indicating success or failure.

    Example:
        save_validated_query(
            name="most_race_wins_2019",
            question="Who won the most races in 2019?",
            query="SELECT name, COUNT(*) AS wins FROM race_wins WHERE ...",
            summary="Counts race wins per driver for a given year",
            notes="Only counts wins, not podiums or points finishes",
            data_quality_notes="Used TO_DATE for date parsing in race_wins table"
        )
    """
    # Validate knowledge base is available
    if _sql_agent_knowledge is None:
        logger.error("Knowledge base not initialized")
        return "Error: Knowledge base not available. Cannot save query."

    # Validate required fields
    if not name or not name.strip():
        return "Error: Query name is required."

    if not question or not question.strip():
        return "Error: Original question is required."

    sql_stripped = (query or "").strip()
    if not sql_stripped:
        return "Error: SQL query is required."

    # Security check: only allow SELECT queries
    sql_lower = sql_stripped.lower().lstrip()
    if not sql_lower.startswith("select") and not sql_lower.startswith("with"):
        return "Error: Only SELECT queries (including CTEs) can be saved."

    # Check for dangerous keywords even in SELECT queries
    dangerous_keywords = [
        "drop",
        "delete",
        "truncate",
        "insert",
        "update",
        "alter",
        "create",
    ]
    for keyword in dangerous_keywords:
        # Check for keyword as whole word (not part of column name)
        if f" {keyword} " in f" {sql_lower} ":
            return f"Error: Query contains potentially dangerous keyword: {keyword}"

    # Build payload
    payload = {
        "name": name.strip(),
        "question": question.strip(),
        "query": sql_stripped,
        "summary": summary.strip() if summary else None,
        "notes": notes.strip() if notes else None,
        "data_quality_notes": data_quality_notes.strip()
        if data_quality_notes
        else None,
    }

    # Remove None values for cleaner storage
    payload = {k: v for k, v in payload.items() if v is not None}

    logger.info(f"Saving validated query to knowledge base: {name}")

    try:
        _sql_agent_knowledge.add_content(
            name=name.strip(),
            text_content=json.dumps(payload, ensure_ascii=False, indent=2),
            reader=TextReader(),
            skip_if_exists=True,
        )
    except Exception as e:
        logger.error(f"Failed to save query: {e}")
        return f"Error: Failed to save query - {e}"

    return f"Successfully saved query '{name}' to knowledge base."
