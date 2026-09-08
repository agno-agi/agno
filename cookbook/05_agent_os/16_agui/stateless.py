"""
Serve an Agent over AG-UI with no database
==========================================

Hold a multi-turn conversation without storing anything on the server. The client
already sends the whole transcript on every AG-UI request, so with no database the
interface forwards it as the agent's history instead of reading a session.

Contrast with basic.py, which stores its sessions and sets add_history_to_context so the
agent reads its own. Frontend tools and confirmations need that database; this file
cannot resume a paused run.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/stateless.py
Try: GET http://localhost:7777/stateless/status, then POST an AG-UI request to
     /stateless/agui with two turns of messages
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create AG-UI AgentOS
# ---------------------------------------------------------------------------

assistant = Agent(
    id="agui-stateless-assistant",
    name="AG-UI Stateless Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Answer clearly and concisely, and refer back to earlier turns when asked.",
)

agent_os = AgentOS(
    id="agui-stateless-os",
    description="An AgentOS whose AG-UI agent keeps no sessions of its own.",
    agents=[assistant],
    interfaces=[AGUI(agent=assistant, prefix="/stateless")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AG-UI Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
