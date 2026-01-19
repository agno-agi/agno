"""
Text-to-SQL Tools Package
=========================

Custom tools for the Text-to-SQL agent.

Tools:
    save_validated_query: Save a validated SQL query to the knowledge base
        for future retrieval. Enables the self-learning loop.

    set_knowledge: Initialize the knowledge base reference. Called by agent.py
        after creating the knowledge instance to avoid circular imports.

Usage:
    from tools import save_validated_query, set_knowledge

    # In agent.py, after creating knowledge:
    set_knowledge(sql_agent_knowledge)

    # The agent uses save_validated_query as a tool:
    sql_agent = Agent(
        tools=[save_validated_query, ...],
        ...
    )
"""

from .save_query import save_validated_query, set_knowledge

__all__ = ["save_validated_query", "set_knowledge"]
