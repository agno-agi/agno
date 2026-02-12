"""Save validated SQL queries to knowledge base."""

import json

from agno.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.tools import tool
from agno.utils.log import logger


def create_save_validated_query_tool(knowledge: Knowledge):
    """Create save_validated_query tool with knowledge injected."""

    @tool
    def save_validated_query(
        name: str,
        question: str,
        query: str,
        summary: str | None = None,
        tables_used: list[str] | None = None,
        data_quality_notes: str | None = None,
    ) -> str:
        """Save a validated SQL query to knowledge base.

        Call ONLY after query executed successfully and user confirmed results.

        Args:
            name: Short name (e.g., "championship_wins_by_driver")
            question: Original user question
            query: The SQL query
            summary: What the query does
            tables_used: Tables used
            data_quality_notes: Data quality issues handled
        """
        if not name or not name.strip():
            return "Error: Name required."
        if not question or not question.strip():
            return "Error: Question required."
        if not query or not query.strip():
            return "Error: Query required."

        sql = query.strip().lower()
        if not sql.startswith("select") and not sql.startswith("with"):
            return "Error: Only SELECT queries can be saved."

        dangerous = [
            "drop",
            "delete",
            "truncate",
            "insert",
            "update",
            "alter",
            "create",
        ]
        for kw in dangerous:
            if f" {kw} " in f" {sql} ":
                return f"Error: Query contains dangerous keyword: {kw}"

        payload = {
            "type": "validated_query",
            "name": name.strip(),
            "question": question.strip(),
            "query": query.strip(),
            "summary": summary.strip() if summary else None,
            "tables_used": tables_used or [],
            "data_quality_notes": data_quality_notes.strip()
            if data_quality_notes
            else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            knowledge.insert(
                name=name.strip(),
                text_content=json.dumps(payload, ensure_ascii=False, indent=2),
                reader=TextReader(),
                skip_if_exists=True,
            )
            return f"Saved query '{name}' to knowledge base."
        except (AttributeError, TypeError, ValueError, OSError) as e:
            logger.error(f"Failed to save query: {e}")
            return f"Error: {e}"

    return save_validated_query
