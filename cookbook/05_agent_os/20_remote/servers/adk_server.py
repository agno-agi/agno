"""
Serve a Google ADK Agent through A2A JSON-RPC
=============================================

Google ADK exposes one Agent as a standard A2A JSON-RPC application. The
custom Agent card advertises streaming and the root RPC URL used by Agno's
RemoteAgent.

Prerequisites: GOOGLE_API_KEY, `google-adk`, and `a2a-sdk[http-server]`
Run: use the isolated Google ADK command in `20_remote/README.md`
Try: fetch GET http://127.0.0.1:8001/.well-known/agent-card.json
"""

from a2a.types import AgentCapabilities, AgentCard
from google.adk import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a

PORT = 8001

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

facts_agent = Agent(
    name="facts_agent",
    model="gemini-3.5-flash",
    description="A Google ADK Agent that explains durable scientific facts.",
    instruction=(
        "Answer with one accurate scientific fact. Keep the answer to two sentences."
    ),
)

# ---------------------------------------------------------------------------
# Create A2A Application
# ---------------------------------------------------------------------------

agent_card = AgentCard(
    name="facts_agent",
    description="A Google ADK Agent that explains durable scientific facts.",
    url=f"http://127.0.0.1:{PORT}",
    version="1.0.0",
    capabilities=AgentCapabilities(
        streaming=True,
        push_notifications=False,
        state_transition_history=False,
    ),
    skills=[],
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
)

app = to_a2a(
    facts_agent,
    host="127.0.0.1",
    port=PORT,
    agent_card=agent_card,
)

# ---------------------------------------------------------------------------
# Run A2A Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
