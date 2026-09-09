"""
Use Backend and Frontend Tools over AG-UI
=========================================

Expose one server-side weather tool and accept a browser-side
change_background tool supplied in an AG-UI request. Frontend tools pause for
external execution; backend tools execute in Python.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_tools.py
Try: POST "Check the weather in London" or supply change_background to /tools/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Backend Tool and AG-UI Agent
# ---------------------------------------------------------------------------


@tool
def get_weather(location: str) -> dict:
    """Get representative weather data for a city."""
    weather = {
        "London": {
            "city": "London",
            "temperature_c": 15,
            "humidity_percent": 80,
            "conditions": "Overcast",
        },
        "Tokyo": {
            "city": "Tokyo",
            "temperature_c": 26,
            "humidity_percent": 70,
            "conditions": "Rainy",
        },
    }
    return weather.get(
        location,
        {
            "city": location,
            "temperature_c": 20,
            "humidity_percent": 60,
            "conditions": "Partly cloudy",
        },
    )


db = SqliteDb(
    id="agui-tools-db",
    db_file="tmp/agui_tools.db",
)

tools_agent = Agent(
    id="agui-tools-agent",
    name="AG-UI Tools Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[get_weather],
    instructions=[
        "Use get_weather for weather questions.",
        (
            "A connected frontend may provide a change_background tool. "
            "When it is available and the user asks for a background change, "
            "call it with a CSS color or gradient."
        ),
        "Briefly summarize completed tool work.",
    ],
)

agent_os = AgentOS(
    id="agui-tools-os",
    description="AG-UI with server tools and request-scoped frontend tools.",
    agents=[tools_agent],
    interfaces=[AGUI(agent=tools_agent, prefix="/tools")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Tools Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
