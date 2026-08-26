"""
Mount AgentOS on an existing FastAPI application
================================================

Pass an existing FastAPI instance through ``base_app`` so its routes and the
AgentOS routes share one process.

Prerequisites: none for the serve-and-curl flow below (OPENAI_API_KEY only
if you send the agent a run)
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/basic.py
Try: curl http://localhost:7777/customers
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Create Base Application and AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="custom-base-app-db",
    db_file="tmp/agent_os_custom_base_app.db",
)

support_agent = Agent(
    id="custom-base-app-agent",
    name="Custom Base App Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer support questions clearly and concisely.",
)

base_app = FastAPI(
    title="Company API",
    version="1.0.0",
)


@base_app.get("/customers")
async def get_customers() -> list[dict[str, object]]:
    """Return a route owned by the original FastAPI application."""
    return [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Grace"},
    ]


agent_os = AgentOS(
    id="custom-base-app-os",
    db=db,
    agents=[support_agent],
    base_app=base_app,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Base Application and AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7777)
