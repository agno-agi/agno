from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.openweather import OpenWeatherTools

weather_agent = Agent(
    id="weather-reporter-agent",
    name="Weather Reporter Agent",
    description="An agent that provides up-to-date weather information for any city.",
    model=OpenAIChat(id="gpt-4o-mini"),
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

if __name__ == "__main__":
    """Run your AgentOS.
    You can run the Agent via A2A protocol:
    POST http://localhost:7770/agents/{id}/v1/message:send
    For streaming responses:
    POST http://localhost:7770/agents/{id}/v1/message:stream
    Retrieve the agent card at:
    GET  http://localhost:7770/agents/{id}/.well-known/agent-card.json
    """
    agent_os.serve(app="weather_agent:app", port=7770, reload=True)
