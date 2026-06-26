"""
Backend Tool Rendering — Dojo Demo
===================================

Backend tool: get_weather (renders as weather card via useRenderTool)

Dojo expects get_weather(location: str) with detailed return:
- city, temperature, humidity, wind_speed, conditions
- Rendered as a styled weather card in the frontend
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool


@tool
def get_weather(location: str) -> dict:
    """Get detailed weather for a location. Returns structured data for frontend rendering."""
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


backend_tool_agent = Agent(
    name="backend_tool_rendering",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[get_weather],
    instructions="""You help users check weather. When asked about weather, always use the get_weather tool.

The tool returns structured data that the frontend will render as a weather card.""",
    markdown=True,
)
