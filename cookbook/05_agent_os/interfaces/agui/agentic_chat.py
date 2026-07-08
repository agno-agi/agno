"""
Agentic Chat — Dojo Demo
========================

Frontend tool: change_background (external_execution)
Backend tool: get_weather (renders as card via useRenderTool)

Dojo expects:
- change_background(background: str) -> changes CSS background
- get_weather(location: str) -> dict with city, temperature, humidity, wind_speed, conditions
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool


@tool(external_execution=True, external_execution_silent=True)
def change_background(background: str) -> str:
    """Change the background color of the chat. Can be anything that the CSS background attribute accepts. Regular colors, linear or radial gradients etc."""
    return f"Background changed to {background}"


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
    tools=[change_background, get_weather],
    instructions="""You are a helpful assistant with frontend and backend capabilities.

Tools available:
- change_background: Changes the page background. Accepts CSS values (colors, gradients). Only use when explicitly asked.
- get_weather: Gets weather for a location. Returns temperature, humidity, wind speed, and conditions.

Be helpful and use tools when appropriate.""",
    markdown=True,
)
