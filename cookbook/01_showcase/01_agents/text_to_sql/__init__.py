"""
Text-to-SQL Agent
=================

A self-learning SQL agent that queries Formula 1 data (1950-2020) and improves
through accumulated knowledge.

This tutorial demonstrates:
- Semantic model for table discovery
- Knowledge-based query generation
- Handling data quality issues without fixing the data
- Self-learning through validated query storage
- Agentic memory for user preferences

Quick Start:
    # Check setup
    python scripts/check_setup.py

    # Run basic examples
    python examples/basic_queries.py

    # Interactive mode
    from agent import sql_agent
    sql_agent.cli_app(stream=True)

Example:
    >>> from agent import sql_agent
    >>> sql_agent.print_response("Who won the most races in 2019?", stream=True)
"""

from .agent import DB_URL, demo_db, sql_agent, sql_agent_knowledge
from .semantic_model import SEMANTIC_MODEL, SEMANTIC_MODEL_STR

__all__ = [
    "sql_agent",
    "sql_agent_knowledge",
    "DB_URL",
    "demo_db",
    "SEMANTIC_MODEL",
    "SEMANTIC_MODEL_STR",
]
