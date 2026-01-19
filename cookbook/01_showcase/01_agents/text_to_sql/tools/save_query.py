"""
Save Validated Query Tool
=========================

Custom tool for saving validated SQL queries to the knowledge base.
Uses a module-level variable to avoid circular import issues.
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
    query: Optional[str] = None,
    summary: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Save a validated SQL query and its explanation to the knowledge base.

    Args:
        name: The name of the query.
        question: The original question asked by the user.
        summary: Optional short explanation of what the query does and returns.
        query: The exact SQL query that was executed.
        notes: Optional caveats, assumptions, or data-quality considerations.

    Returns:
        str: Status message.
    """
    if _sql_agent_knowledge is None:
        return "Knowledge not available"

    sql_stripped = (query or "").strip()
    if not sql_stripped:
        return "No SQL provided"

    # Basic safety: only allow SELECT to be saved
    if not sql_stripped.lower().lstrip().startswith("select"):
        return "Only SELECT queries can be saved"

    payload = {
        "name": name,
        "question": question,
        "query": query,
        "summary": summary,
        "notes": notes,
    }

    logger.info("Saving validated SQL query to knowledge base")

    _sql_agent_knowledge.insert(
        name=name,
        text_content=json.dumps(payload, ensure_ascii=False),
        reader=TextReader(),
        skip_if_exists=True,
    )

    return "Saved validated query to knowledge base"
