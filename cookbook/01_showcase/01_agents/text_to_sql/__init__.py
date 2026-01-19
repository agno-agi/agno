"""
Text-to-SQL Tutorial
====================

A production-ready Text-to-SQL tutorial demonstrating a self-learning SQL agent
that queries F1 data and improves through accumulated knowledge.

Quick Start:
    1. Start PostgreSQL: ./cookbook/scripts/run_pgvector.sh
    2. Load F1 data: python scripts/load_f1_data.py
    3. Load knowledge: python scripts/load_knowledge.py
    4. Run examples: python examples/01_basic_queries.py

Exports:
    sql_agent: The configured SQL agent
    sql_agent_knowledge: Knowledge base for the agent
    DB_URL: Database connection string
"""

from .agent import DB_URL, demo_db, sql_agent, sql_agent_knowledge

__all__ = [
    "sql_agent",
    "sql_agent_knowledge",
    "DB_URL",
    "demo_db",
]
