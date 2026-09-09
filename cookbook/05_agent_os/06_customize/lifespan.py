"""
Update AgentOS from a custom application lifespan
=================================================

AgentOS detects a lifespan parameter named ``agent_os`` and injects the active
instance. At startup this example appends a second agent and calls
``agent_os.resync(app)`` so the discovery document and routers reflect the
updated component set. Shutdown uses the same lifespan for cleanup.

Prerequisites: none for the serve-and-curl flow below (OPENAI_API_KEY only
if you send the agent a run)
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/lifespan.py
Try: curl http://localhost:7777/config
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Create Lifespan-Managed AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="custom-lifespan-db",
    db_file="tmp/agent_os_custom_lifespan.db",
)

initial_agent = Agent(
    id="initial-agent",
    name="Initial Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

startup_agent = Agent(
    id="startup-agent",
    name="Startup Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
    agent_os: AgentOS,
) -> AsyncIterator[None]:
    """Add a component at startup, resync AgentOS, and mark clean shutdown."""
    print("Lifespan startup: adding startup-agent")
    if agent_os.agents is None:
        agent_os.agents = []
    if all(agent.id != startup_agent.id for agent in agent_os.agents):
        agent_os.agents.append(startup_agent)
    agent_os.resync(app=app)
    app.state.lifespan_ready = True
    yield
    app.state.lifespan_ready = False
    print("Lifespan shutdown: cleanup complete")


agent_os = AgentOS(
    id="custom-lifespan-os",
    db=db,
    agents=[initial_agent],
    lifespan=lifespan,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Lifespan-Managed AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7777)
