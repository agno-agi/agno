"""
Multiple Context Providers on One Agent
=======================================

Three providers on one agent — filesystem, web (Exa's keyless MCP),
and an in-memory SQLite DB. Each provider contributes its own
`query_<id>` tool; the agent picks which to call based on the
question.

Shows that `get_tools()` composes cleanly across providers: no name
collisions, each source stays in its own namespace. Also shows the
lifecycle story: only the web provider needs `asetup`/`aclose`
(its MCP session), and the caller brackets just that one.

Requires:
    OPENAI_API_KEY
    (optional) EXA_API_KEY  raises the Exa MCP rate ceiling
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.context.database import DatabaseContextProvider
from agno.context.fs import FilesystemContextProvider
from agno.context.web import ExaMCPBackend, WebContextProvider
from agno.models.openai import OpenAIResponses
from sqlalchemy import create_engine, text

# Every provider sub-agent in this cookbook shares the same small model.
provider_model = OpenAIResponses(id="gpt-5.4-mini")

# ---------------------------------------------------------------------------
# Provider 1: filesystem (this cookbook's directory)
# ---------------------------------------------------------------------------
fs = FilesystemContextProvider(
    root=Path(__file__).resolve().parent,
    id="cookbooks",
    name="Cookbooks",
    model=provider_model,
)

# ---------------------------------------------------------------------------
# Provider 2: web (Exa's keyless MCP)
# ---------------------------------------------------------------------------
web = WebContextProvider(backend=ExaMCPBackend(), model=provider_model)

# ---------------------------------------------------------------------------
# Provider 3: tiny SQLite DB with releases
#
# Using a temp file rather than `sqlite:///:memory:` because the
# in-memory DB is per-connection — the sub-agent opens its own
# connection and would see an empty DB.
# ---------------------------------------------------------------------------
DB_PATH = Path(tempfile.gettempdir()) / "agno_context_multi_provider.sqlite"
if DB_PATH.exists():
    DB_PATH.unlink()
engine = create_engine(f"sqlite:///{DB_PATH}")
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
    id="releases",
    name="Release Notes DB",
    sql_engine=engine,
    readonly_engine=engine,
    model=provider_model,
)

# ---------------------------------------------------------------------------
# Compose the tools across all three providers
# ---------------------------------------------------------------------------
tools = [*fs.get_tools(), *web.get_tools(), *db.get_tools()]
guidance = "\n".join([fs.instructions(), web.instructions(), db.instructions()])

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=tools,
    instructions=(
        "You have three tools available — a filesystem over this cookbook "
        "directory, web search, and a small releases database. Pick the "
        "right one for each sub-question; you may call more than one.\n\n" + guidance
    ),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent — bracket the web provider's MCP session with
# asetup/aclose. fs and db have no async resources so they don't need it.
# ---------------------------------------------------------------------------
async def main() -> None:
    await web.asetup()
    try:
        print(f"\nfs.status()  = {fs.status()}")
        print(f"web.status() = {web.status()}")
        print(f"db.status()  = {db.status()}\n")
        prompt = (
            "Two things: (a) what cookbook files live in this directory, "
            "and (b) what is the current version listed in the releases "
            "database? Answer both parts."
        )
        print(f"> {prompt}\n")
        await agent.aprint_response(prompt)
    finally:
        await web.aclose()


if __name__ == "__main__":
    asyncio.run(main())
