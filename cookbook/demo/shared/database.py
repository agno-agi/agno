"""Shared database configuration for Real-World Showcase demo"""

from agno.db.sqlite.sqlite import SqliteDb

# Shared database instance used by all agents, teams, and workflows
db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")
