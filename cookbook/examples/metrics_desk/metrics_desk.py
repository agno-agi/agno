"""
Metrics Desk
============
Your production database, answerable from any MCP client, without your credentials
or your rows leaving your process. The client sends a question, this process runs
the SQL over a read-only connection, and only the answer crosses the wire.

Run this file, point an MCP client at http://localhost:7777/mcp, and ask for
revenue by region. Then ask it to delete the table: the SQLite driver refuses the
write, so the guarantee does not depend on the model behaving.
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPServerConfig
from agno.tools.sql import SQLTools
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# The warehouse
# ---------------------------------------------------------------------------
# Stand in for your production database. Seeded once with a writable engine,
# then never opened for writing again.
WAREHOUSE = Path("tmp/shop.db")
WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)

if not WAREHOUSE.exists():
    seed = create_engine(f"sqlite:///{WAREHOUSE}")
    with seed.begin() as conn:
        conn.execute(text("CREATE TABLE orders (day TEXT, region TEXT, amount REAL)"))
        conn.execute(
            text(
                "INSERT INTO orders VALUES"
                " ('2026-07-20', 'emea', 120.0),"
                " ('2026-07-20', 'us', 340.5),"
                " ('2026-07-21', 'emea', 96.25),"
                " ('2026-07-21', 'us', 512.0),"
                " ('2026-07-21', 'apac', 78.4)"
            )
        )
    seed.dispose()

# mode=ro is enforced by the SQLite driver, below the agent and below the SQL it
# writes. A write on this engine raises "attempt to write a readonly database".
warehouse = create_engine(f"sqlite:///file:{WAREHOUSE}?mode=ro&uri=true")

# ---------------------------------------------------------------------------
# Create the Analyst
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/metrics_desk.db")

analyst = Agent(
    id="analyst",
    name="Analyst",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[SQLTools(db_engine=warehouse)],
    instructions=[
        "Answer questions about the orders table by running SQL.",
        "Report the number you measured and the query you ran. Never estimate a value.",
        "Run the SQL you are asked for, including writes. The connection is read-only,",
        "so the database decides what is allowed. Report any error verbatim.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# The MCP surface
# ---------------------------------------------------------------------------
# One tool is exposed to the outside world. The connection string, the schema and
# the rows stay in this process; the client only ever sees the answer.
async def ask_metrics(question: str) -> str:
    """Ask a question about the company's live orders database."""
    run = await analyst.arun(question)
    return run.content or ""


agent_os = AgentOS(
    id="metrics-desk",
    db=db,
    agents=[analyst],
    mcp_server=MCPServerConfig(tools=[ask_metrics], enable_builtin_tools=False),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="metrics_desk:app")
