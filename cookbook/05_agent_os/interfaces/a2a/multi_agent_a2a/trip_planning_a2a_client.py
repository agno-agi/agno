"""
Trip Planning A2A Client
========================

A Trip Planner Agno agent that orchestrates two specialised Agno agents
(airbnb_agent on 7774, weather_agent on 7770) over A2A 1.0 using
`A2AClient` — one toolkit instance per remote agent. Each instance
exposes tools named after its remote agent
(`send_message_to_weather_reporter_agent`,
`send_message_to_airbnb_search_agent`, ...), so the LLM sees one clearly
named tool per specialist.

Prerequisites:
    .venvs/demo/bin/python -m pip install -U "a2a-sdk>=1.0"

Run the three servers in three terminals:
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/airbnb_agent.py
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/weather_agent.py
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/trip_planning_a2a_client.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.a2a import A2AClient

# One A2AClient instance per remote agent — each fetches its agent's
# card from the URL and derives its tool names from the URL slug.
weather_agent_tools = A2AClient(
    url="http://localhost:7770/a2a/agents/weather-reporter-agent"
)
airbnb_agent_tools = A2AClient(
    url="http://localhost:7774/a2a/agents/airbnb-search-agent"
)

trip_planner = Agent(
    name="Trip Planner",
    id="trip_planner",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[weather_agent_tools, airbnb_agent_tools],
    markdown=True,
    description="You are an expert Trip Planner orchestrator.",
    instructions=[
        "You help users plan complete trips by coordinating with specialized remote agents over A2A.",
        "1. Always check the weather for the destination/dates FIRST using `send_message_to_weather_reporter_agent`.",
        "2. Based on the weather suitability, search for accommodation using `send_message_to_airbnb_search_agent`.",
        "3. Synthesize the information from both agents into a final itinerary proposal.",
        "You can inspect a remote agent's skills with its `get_*_card` tool.",
        "If a remote call returns an error, inform the user and proceed with the available information.",
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
        POST http://localhost:7777/a2a/agents/trip_planner/v1     (JSON-RPC: SendMessage / SendStreamingMessage / GetTask / CancelTask — what the a2a-sdk Client targets)
        POST http://localhost:7777/a2a/agents/trip_planner/v1/message:send   (legacy URL-style)
        POST http://localhost:7777/a2a/agents/trip_planner/v1/message:stream (legacy URL-style)
    """
    agent_os.serve(app="trip_planning_a2a_client:app", port=7777, reload=True)
