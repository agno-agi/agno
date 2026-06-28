"""
Trip Planning A2A Client
========================

A Trip Planner Agno agent that orchestrates two specialised Agno agents
(airbnb_agent on 7774, weather_agent on 7770) via the canonical A2A 1.0
client from the `a2a-sdk` package. Demonstrates that an Agno-hosted A2A
server speaks the same protocol any modern A2A client expects.

Prerequisites:
    .venvs/demo/bin/python -m pip install -U "a2a-sdk>=1.0"

Run the three servers in three terminals:
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/airbnb_agent.py
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/weather_agent.py
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/trip_planning_a2a_client.py
"""

from uuid import uuid4

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest

# Base URL points at the agent — `create_client` fetches /.well-known/agent-card.json
# from here, and the card itself advertises the JSON-RPC interface URL (with /v1)
# that the SDK then POSTs operations to.
AIRBNB_BASE_URL = "http://localhost:7774/a2a/agents/airbnb-search-agent"
WEATHER_BASE_URL = "http://localhost:7770/a2a/agents/weather-reporter-agent"


def _extract_text_from_history(task) -> str:
    if not task.history:
        return ""
    last = task.history[-1]
    return "".join(p.text for p in last.parts if p.WhichOneof("content") == "text")


async def _send_to_a2a_agent(base_url: str, text: str) -> str:
    """Send a user message via the a2a-sdk client and return the agent's final response.

    The SDK streams `status_update` + `artifact_update` events while the agent
    runs, then a final `task` event when the run completes. We only need the
    final task here; the orchestrator agent doesn't surface intermediate
    progress to its caller.
    """
    request = SendMessageRequest(
        message=Message(
            message_id=str(uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=text, media_type="text/plain")],
        )
    )
    try:
        client = await create_client(base_url)
        async with client:
            async for response in client.send_message(request):
                if response.WhichOneof("payload") == "task":
                    return (
                        _extract_text_from_history(response.task)
                        or "(no text in task history)"
                    )
    except Exception as e:
        return f"Connection Error: Could not talk to agent at {base_url}. Details: {e}"
    return f"System Error: No final task received from {base_url}."


async def ask_airbnb_agent(request: str) -> str:
    """Contact the specialised Airbnb Agent to find listings or get details.

    Args:
        request (str): A natural language request (e.g., "Find a 2-bed apartment in Paris for under $200").
    """
    return await _send_to_a2a_agent(AIRBNB_BASE_URL, request)


async def ask_weather_agent(request: str) -> str:
    """Contact the specialised Weather Agent to get forecasts or current conditions.

    Args:
        request (str): A natural language request (e.g., "What is the weather in Tokyo next week?").
    """
    return await _send_to_a2a_agent(WEATHER_BASE_URL, request)


trip_planner = Agent(
    name="Trip Planner",
    id="trip_planner",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[ask_airbnb_agent, ask_weather_agent],
    markdown=True,
    description="You are an expert Trip Planner orchestrator.",
    instructions=[
        "You help users plan complete trips by coordinating with specialized agents.",
        "1. Always check the weather for the destination/dates FIRST using 'ask_weather_agent'.",
        "2. Based on the weather suitability, search for accommodation using 'ask_airbnb_agent'.",
        "3. Synthesize the information from both agents into a final itinerary proposal.",
        "If an agent returns an error, inform the user and try to proceed with the available information.",
    ],
)

agent_os = AgentOS(
    id="trip-planning-service",
    description="AgentOS hosting the Trip Planning Orchestrator.",
    agents=[trip_planner],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run the orchestrator.

    The orchestrator is itself an A2A 1.0 server — point another a2a-sdk
    client at it the same way it talks to its tools:
        GET  http://localhost:7777/a2a/agents/trip_planner/.well-known/agent-card.json
        POST http://localhost:7777/a2a/agents/trip_planner/v1     (JSON-RPC: SendMessage / SendStreamingMessage)
        POST http://localhost:7777/a2a/agents/trip_planner/v1/message:send   (legacy URL-style)
        POST http://localhost:7777/a2a/agents/trip_planner/v1/message:stream (legacy URL-style)
    """
    agent_os.serve(app="trip_planning_a2a_client:app", port=7777, reload=True)
