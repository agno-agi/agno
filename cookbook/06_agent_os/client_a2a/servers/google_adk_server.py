"""Google ADK A2A Server for testing A2AClient.

This server uses Google's Agent Development Kit (ADK) to create an A2A-compatible
agent that can be tested with Agno's A2AClient.

Prerequisites:
    pip install google-adk a2a-sdk uvicorn
    export GOOGLE_API_KEY=your_key

Usage:
    python cookbook/06_agent_os/client_a2a/servers/google_adk_server.py

The server will start at http://localhost:8001
"""

import os

from google.adk import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.tools import google_search

agent = Agent(
    name="facts_agent",
    model="gemini-2.5-flash-lite",
    description="Agent that provides interesting facts using Google Search.",
    instruction="You are a helpful agent who can provide interesting facts. "
    "Use Google Search to find accurate and up-to-date information when needed.",
    tools=[google_search],
)

app = to_a2a(agent, port=int(os.getenv("PORT", "8001")))

if __name__ == "__main__":
    import uvicorn

    print("Server URL: http://localhost:8001")
    uvicorn.run(app, host="localhost", port=8001)
