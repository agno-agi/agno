"""
Weather Agent
=============

Demonstrates weather agent.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.openweather import OpenWeatherTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

weather_agent = Agent(
    id="weather-reporter-agent",
    name="Weather Reporter Agent",
    description="An agent that provides up-to-date weather information for any city.",
    model=OpenAIChat(id="gpt-5.2"),
    tools=[
        OpenWeatherTools(
            units="standard"  # Can be 'standard', 'metric', 'imperial'
        )
    ],
    instructions=dedent("""
        You are a concise weather reporter.
        Use the 'get_current_weather' tool to fetch current conditions.
        Respond with the temperature and a brief summary.
    """),
    markdown=True,
)
agent_os = AgentOS(
    id="weather-agent-os",
    description="An AgentOS serving specialized Agent for weather Reporting",
    agents=[
        weather_agent,
    ],
    a2a_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS with the A2A 1.0 interface.

    Endpoints (A2A 1.0, JSON-RPC 2.0 envelope, flat Part with mediaType):
        GET  http://localhost:7770/a2a/agents/weather-reporter-agent/.well-known/agent-card.json
        POST http://localhost:7770/a2a/agents/weather-reporter-agent/v1                 (JSON-RPC: SendMessage / SendStreamingMessage)
        POST http://localhost:7770/a2a/agents/weather-reporter-agent/v1/message:send    (legacy URL-style)
        POST http://localhost:7770/a2a/agents/weather-reporter-agent/v1/message:stream  (legacy URL-style)

    Targeted by `streaming_client_demo.py` and `agent_card_demo.py`.
    """
    agent_os.serve(app="weather_agent:app", port=7770, reload=True)
