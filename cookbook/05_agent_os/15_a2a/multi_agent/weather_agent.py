"""
Serve a Weather Specialist over A2A
===================================

Expose a weather Agent on the dedicated topology port. The trip planner calls
this Agent through the official A2A client at the entity-scoped URL.

Prerequisites: OPENAI_API_KEY, OPENWEATHER_API_KEY, and the `agno[a2a]` extra
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/multi_agent/weather_agent.py
Try: Fetch GET http://127.0.0.1:7782/a2a/agents/weather-agent/.well-known/agent-card.json
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.openweather import OpenWeatherTools

# ---------------------------------------------------------------------------
# Create Weather Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="a2a-weather-db",
    db_file="tmp/a2a_weather.db",
)

weather_agent = Agent(
    id="weather-agent",
    name="Weather Agent",
    description="An A2A specialist for current weather conditions.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[
        OpenWeatherTools(
            units="metric",
            enable_forecast=False,
            enable_air_pollution=False,
            enable_geocoding=False,
        )
    ],
    instructions=[
        "Use get_current_weather for the requested destination.",
        "Return the location, temperature, conditions, and one practical note.",
        "If the weather service returns an error, report it clearly.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="a2a-weather-os",
    description="AgentOS serving the weather specialist.",
    agents=[weather_agent],
    a2a_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Weather AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7782)
