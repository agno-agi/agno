"""
Google ADK agent with tool calls, wrapped in Agno's GoogleADKAgent.

ADK turns plain Python functions into tools. Agno shows each call and its
result as tool events while the answer streams.

Requirements:
    pip install google-adk
    export GOOGLE_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/google_adk/google_adk_tools.py
"""

from agno.agents.google_adk import GoogleADKAgent
from google.adk.agents import LlmAgent


# ----- Define tools -----
def get_weather(city: str) -> dict:
    """Get the current weather for a city."""
    data = {
        "Paris": {"temp": "18C", "condition": "Sunny"},
        "London": {"temp": "12C", "condition": "Cloudy"},
        "Tokyo": {"temp": "22C", "condition": "Clear"},
    }
    return data.get(city, {"temp": "unknown", "condition": "unknown"})


def get_population(city: str) -> str:
    """Get the population of a city."""
    data = {
        "Paris": "2.1 million",
        "London": "8.9 million",
        "Tokyo": "13.9 million",
    }
    return data.get(city, "unknown")


# ----- Build an ADK agent with tools -----
adk_agent = LlmAgent(
    name="city_agent",
    model="gemini-3.7-flash",
    instruction="Use the tools to answer questions about cities. Call both tools when both facts are asked for.",
    tools=[get_weather, get_population],
)

# ----- Wrap for Agno -----
agent = GoogleADKAgent(
    name="ADK Tool Agent",
    agent=adk_agent,
)

# Streaming with tool calls visible
result = agent.print_response(
    "What's the weather and population of Tokyo?", stream=True
)
print("Tools called:", [tool.tool_name for tool in result.tools or []])
