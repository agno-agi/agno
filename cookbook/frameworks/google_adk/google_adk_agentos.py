"""
Run a Google ADK agent through AgentOS endpoints.

This registers an ADK agent with AgentOS, so it gets the same HTTP API,
SSE streaming, session storage and UI as native Agno agents.

Requirements:
    pip install google-adk
    export GOOGLE_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/google_adk/google_adk_agentos.py

Then call the API:
    # Streaming
    curl -X POST http://localhost:7777/agents/adk-assistant/runs \\
        -F "message=What is the weather in Paris?" \\
        -F "stream=true" \\
        --no-buffer

    # Non-streaming
    curl -X POST http://localhost:7777/agents/adk-assistant/runs \\
        -F "message=What is the weather in Paris?" \\
        -F "stream=false"

    # List agents
    curl http://localhost:7777/agents
"""

from agno.agents.google_adk import GoogleADKAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from google.adk.agents import LlmAgent


def get_weather(city: str) -> dict:
    """Get the current weather for a city."""
    data = {
        "Paris": {"temp": "18C", "condition": "Sunny"},
        "London": {"temp": "12C", "condition": "Cloudy"},
        "Tokyo": {"temp": "22C", "condition": "Clear"},
    }
    return data.get(city, {"temp": "unknown", "condition": "unknown"})


adk_agent = LlmAgent(
    name="assistant",
    model="gemini-3.7-flash",
    instruction="You are a helpful assistant. Use the weather tool when asked about the weather.",
    tools=[get_weather],
)

agent = GoogleADKAgent(
    name="ADK Assistant",
    description="A Google ADK agent served through AgentOS",
    agent=adk_agent,
    db=SqliteDb(db_file="tmp/agentos.db"),
)

agent_os = AgentOS(
    name="Google ADK Agent Example",
    description="AgentOS serving a Google ADK agent",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="google_adk_agentos:app", reload=True)
