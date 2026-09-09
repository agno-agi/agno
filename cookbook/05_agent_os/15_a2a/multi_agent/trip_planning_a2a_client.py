"""
Orchestrate Multiple A2A Agents
===============================

Serve a trip-planning Agent whose async tools call the weather and Airbnb
specialists through the first-party `A2AClient`. `TaskResult.content` is the
already-unwrapped downstream response.

Prerequisites: Start weather_agent.py on 7782 and airbnb_agent.py on 7783, then set OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/multi_agent/trip_planning_a2a_client.py
Try: With all servers running, rerun this file with --demo to call POST http://127.0.0.1:7779/a2a/agents/trip-planner/v1/message:send
"""

import asyncio
import os
import sys

from agno.agent import Agent
from agno.client.a2a import A2AClient, TaskResult
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Downstream A2A Clients
# ---------------------------------------------------------------------------

WEATHER_URL = os.getenv(
    "WEATHER_A2A_URL",
    "http://127.0.0.1:7782/a2a/agents/weather-agent",
)
AIRBNB_URL = os.getenv(
    "AIRBNB_A2A_URL",
    "http://127.0.0.1:7783/a2a/agents/airbnb-agent",
)
TRIP_PLANNER_URL = "http://127.0.0.1:7779/a2a/agents/trip-planner"

weather_client = A2AClient(WEATHER_URL, timeout=90)
airbnb_client = A2AClient(AIRBNB_URL, timeout=90)


def response_content(result: TaskResult, service: str) -> str:
    """Return the SDK-unwrapped content or fail with the downstream status."""
    if not result.is_completed:
        raise RuntimeError(f"{service} A2A task ended with status {result.status}")
    if not result.content.strip():
        raise RuntimeError(f"{service} A2A task returned no content")
    return result.content


async def ask_weather_agent(request: str) -> str:
    """Ask the weather specialist through A2A."""
    result = await weather_client.send_message(request)
    return response_content(result, "Weather")


async def ask_airbnb_agent(request: str) -> str:
    """Ask the Airbnb specialist through A2A."""
    result = await airbnb_client.send_message(request)
    return response_content(result, "Airbnb")


# ---------------------------------------------------------------------------
# Create Trip Planner
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="a2a-trip-planner-db",
    db_file="tmp/a2a_trip_planner.db",
)

trip_planner = Agent(
    id="trip-planner",
    name="Trip Planner",
    description="An orchestrator that coordinates weather and accommodation A2A Agents.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[ask_weather_agent, ask_airbnb_agent],
    instructions=[
        "Coordinate the weather and Airbnb specialists for every trip request.",
        "Call ask_weather_agent first for the destination.",
        "Then call ask_airbnb_agent for the requested dates and party size.",
        "Synthesize both downstream responses into a compact trip plan.",
        "If one specialist reports an error, identify it and use the other result.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="a2a-trip-planner-os",
    description="AgentOS orchestrating two downstream A2A specialists.",
    agents=[trip_planner],
    a2a_interface=True,
)
app = agent_os.get_app()


async def run_demo() -> None:
    """Call the running orchestrator through its own A2A interface."""
    client = A2AClient(TRIP_PLANNER_URL, timeout=180)
    result = await client.send_message(
        "Plan a two-night Paris trip from 2026-09-10 for two adults. "
        "Check current weather and suggest two stays."
    )
    if not result.is_completed:
        raise RuntimeError(f"Trip planner task ended with status {result.status}")

    print(f"Task ID: {result.task_id}")
    print(f"Context ID: {result.context_id}")
    print(result.content)


# ---------------------------------------------------------------------------
# Run Trip Planner Server or Client Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--demo" in sys.argv:
        asyncio.run(run_demo())
    else:
        agent_os.serve(app=app, port=7779)
