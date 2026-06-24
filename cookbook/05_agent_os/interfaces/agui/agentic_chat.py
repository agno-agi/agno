"""
Agentic Chat — Dojo Demo
========================

Frontend tool: change_background — defined by Dojo via useFrontendTool, sent to backend
    in run_input.tools, automatically converted to external_execution=True Functions
Backend tool: get_weather — defined here, renders as card via useRenderTool on Dojo

The agent only defines backend tools. Frontend tools come from the UI at runtime.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool


@tool
def get_weather(location: str) -> dict:
    """Get the current weather for a location."""
    data = {
        "San Francisco": {
            "city": "San Francisco",
            "temperature": 18,
            "humidity": 65,
            "wind_speed": 12,
            "conditions": "Sunny",
        },
        "New York": {
            "city": "New York",
            "temperature": 22,
            "humidity": 55,
            "wind_speed": 8,
            "conditions": "Cloudy",
        },
        "Tokyo": {
            "city": "Tokyo",
            "temperature": 26,
            "humidity": 70,
            "wind_speed": 5,
            "conditions": "Rainy",
        },
        "London": {
            "city": "London",
            "temperature": 15,
            "humidity": 80,
            "wind_speed": 15,
            "conditions": "Overcast",
        },
        "Paris": {
            "city": "Paris",
            "temperature": 20,
            "humidity": 60,
            "wind_speed": 10,
            "conditions": "Partly cloudy",
        },
    }
    return data.get(
        location,
        {
            "city": location,
            "temperature": 20,
            "humidity": 60,
            "wind_speed": 10,
            "conditions": "Partly cloudy",
        },
    )


agentic_chat_agent = Agent(
    name="agentic_chat",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[get_weather],
    instructions="""You are a helpful assistant.

Use the tools available to help the user. The frontend may provide additional tools
like change_background — use them when the user asks.""",
    markdown=True,
)
