"""Google ADK A2A Server for system tests.

Uses Google's ADK to create an A2A-compatible agent.
Requires GOOGLE_API_KEY environment variable.

This server exposes a facts-agent that provides interesting facts,
using pure JSON-RPC at root "/" endpoint (Google ADK style).
"""

import os

from google.adk import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.tools import google_search

agent = Agent(
    name="facts-agent",
    model="gemini-2.5-flash-lite",
    description="Agent that provides interesting facts.",
    instruction="You are a helpful agent who provides interesting facts.",
    tools=[google_search],
)

app = to_a2a(agent, port=int(os.getenv("PORT", "7003")))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7003)
