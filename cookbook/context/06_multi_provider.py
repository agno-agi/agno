"""
Multiple Context Providers on One Agent
=======================================

Three providers on one agent — filesystem, web (Exa), and an in-memory
SQLite DB. Each provider contributes its own `query_<id>` tool; the
agent picks which to call based on the question.

Shows that `get_tools()` composes cleanly across providers: no name
collisions, each source stays in its own namespace.

Requires:
    OPENAI_API_KEY
    EXA_API_KEY  (for the web provider)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.context.database import DatabaseContextProvider
from agno.context.fs import FilesystemContextProvider
from agno.context.web import ExaBackend, WebContextProvider
from agno.models.openai import OpenAIResponses
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Provider 1: filesystem (this cookbook's directory)
# ---------------------------------------------------------------------------
fs = FilesystemContextProvider(
    root=Path(__file__).resolve().parent, id="cookbooks", name="Cookbooks"
)

# ---------------------------------------------------------------------------
# Provider 2: web (Exa)
# ---------------------------------------------------------------------------
web = WebContextProvider(backend=ExaBackend())

# ---------------------------------------------------------------------------
# Provider 3: tiny in-memory DB with releases
# ---------------------------------------------------------------------------
engine = create_engine("sqlite:///:memory:")
with engine.begin() as conn:
    conn.execute(text("CREATE TABLE releases (version TEXT, notes TEXT)"))
    conn.execute(
        text("INSERT INTO releases VALUES (:v, :n)"),
        [
            {"v": "2.5.17", "n": "agno core release — current"},
            {"v": "2.5.16", "n": "previous release"},
        ],
    )
db = DatabaseContextProvider(
    id="releases", name="Release Notes DB", sql_engine=engine, readonly_engine=engine
)

# ---------------------------------------------------------------------------
# Compose the tools across all three providers
# ---------------------------------------------------------------------------
tools = [*fs.get_tools(), *web.get_tools(), *db.get_tools()]
guidance = "\n".join([fs.instructions(), web.instructions(), db.instructions()])

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=tools,
    instructions=(
        "You have three tools available — a filesystem over this cookbook "
        "directory, web search, and a small releases database. Pick the "
        "right one for each sub-question; you may call more than one.\n\n" + guidance
    ),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\nfs.status()  = {fs.status()}")
    print(f"web.status() = {web.status()}")
    print(f"db.status()  = {db.status()}\n")
    prompt = (
        "Two things: (a) what cookbook files live in this directory, "
        "and (b) what is the current version listed in the releases "
        "database? Answer both parts."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
