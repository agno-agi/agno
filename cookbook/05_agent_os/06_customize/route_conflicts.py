"""
Choose which application owns conflicting routes
================================================

An existing FastAPI app defines ``/`` and ``/health``, which AgentOS also
provides. ``on_route_conflict="preserve_base_app"`` keeps those custom
handlers while AgentOS still registers non-conflicting routes such as
``/config`` and the agent run surface.

Prerequisites: none for the serve-and-curl flow below (OPENAI_API_KEY only
if you send the agent a run)
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/route_conflicts.py
Try: curl http://localhost:7777/health
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Create Conflicting Base Application and AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="route-conflict-db",
    db_file="tmp/agent_os_route_conflicts.db",
)

route_agent = Agent(
    id="route-conflict-agent",
    name="Route Conflict Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

base_app = FastAPI(title="Custom Route Owner")


@base_app.get("/")
async def custom_home() -> dict[str, str]:
    """Return the base application's custom landing page."""
    return {"owner": "base_app", "route": "/"}


@base_app.get("/health")
async def custom_health() -> dict[str, str]:
    """Return the base application's custom health contract."""
    return {"status": "custom_ok", "owner": "base_app"}


agent_os = AgentOS(
    id="route-conflict-os",
    db=db,
    agents=[route_agent],
    base_app=base_app,
    on_route_conflict="preserve_base_app",
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Conflict Policy Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7777)
