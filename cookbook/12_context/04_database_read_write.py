"""
Database Context Provider (SQLite, read + write)
================================================

DatabaseContextProvider exposes two tools to the calling agent:
- `query_<id>(question)`  — natural-language reads via a readonly engine
- `update_<id>(instruction)` — natural-language writes via a writable engine

Two sub-agents under the hood so the read path never sees the write
engine. This cookbook uses a fresh SQLite file seeded with a `contacts`
table, round-trips one insert through `update_<id>`, then reads it
back with `query_<id>`.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.context.database import DatabaseContextProvider
from agno.models.openai import OpenAIResponses
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Seed a SQLite DB with a contacts table
# ---------------------------------------------------------------------------
DB_PATH = Path(tempfile.gettempdir()) / "agno_context_db_cookbook.sqlite"
if DB_PATH.exists():
    DB_PATH.unlink()

db_url = f"sqlite:///{DB_PATH}"
engine = create_engine(db_url)

with engine.begin() as conn:
    conn.execute(
        text(
            "CREATE TABLE contacts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL, "
            "email TEXT, "
            "role TEXT"
            ")"
        )
    )
    conn.execute(
        text("INSERT INTO contacts (name, email, role) VALUES (:n, :e, :r)"),
        {"n": "Ada Lovelace", "e": "ada@example.com", "r": "engineer"},
    )

# ---------------------------------------------------------------------------
# Create the provider — same engine for read + write in this demo
#   (in production, pass a separate readonly engine that can't mutate)
# ---------------------------------------------------------------------------
# Passing an explicit `id` (rather than the default "database") is
# recommended — it scopes the tool names to `query_contacts` /
# `update_contacts`, which keeps collisions away when an agent talks
# to more than one database.
db = DatabaseContextProvider(
    id="contacts",
    sql_engine=engine,
    readonly_engine=engine,
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=db.get_tools(),
    instructions=db.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
async def _run() -> None:
    print(f"\ndb.status() = {db.status()}\n")

    write_prompt = (
        "Add a contact named 'Grace Hopper' with email "
        "'grace@example.com' and role 'admiral' to the contacts table."
    )
    print(f"> {write_prompt}\n")
    await agent.aprint_response(write_prompt)

    print()
    read_prompt = "List every contact in the contacts table with their role."
    print(f"> {read_prompt}\n")
    await agent.aprint_response(read_prompt)

    # Confirm round-trip at the SQL level so the demo fails loudly if the
    # agent skipped the write.
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name, role FROM contacts ORDER BY id")
        ).fetchall()
    print(f"\n[direct SQL] contacts table rows: {rows}")
    assert any(r.name == "Grace Hopper" for r in rows), "write did not persist"
    print("[ok] Grace Hopper was written to the DB")


if __name__ == "__main__":
    asyncio.run(_run())
