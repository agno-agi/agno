"""Use Turso (libSQL) as the database for an Agent.

Setup:
    pip install ddgs sqlalchemy sqlalchemy-libsql openai
    turso db create my-agno-db
    export TURSO_DATABASE_URL="$(turso db show --url my-agno-db)"
    export TURSO_AUTH_TOKEN="$(turso db tokens create my-agno-db)"

Note: sqlalchemy-libsql currently supports Linux and macOS only.
"""

import os

from agno.agent import Agent
from agno.db.turso import TursoDb
from agno.tools.websearch import WebSearchTools

db = TursoDb(
    url=os.environ["TURSO_DATABASE_URL"],
    auth_token=os.environ["TURSO_AUTH_TOKEN"],
)

agent = Agent(
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    agent.print_response("How many people live in Canada?")
