"""
HITL Pattern 1: Tool Confirmation
=================================

Minimal backend agent - tools are defined on the frontend.

The frontend registers a tool via `useHumanInTheLoop` that requires confirmation.
When the agent calls it, the frontend renders approve/reject UI.

This demonstrates the recommended pattern: frontend defines HITL behavior,
backend just provides the agent.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# Minimal agent - NO backend tools
# Tools come from frontend via useHumanInTheLoop
confirmation_agent = Agent(
    name="tool_confirmation",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_hitl_confirmation.db"),
    instructions=(
        "You help users with tasks that may require confirmation. "
        "Use available tools when needed - they are provided by the frontend."
    ),
    markdown=True,
)

agent_os = AgentOS(
    agents=[confirmation_agent],
    interfaces=[AGUI(agent=confirmation_agent, prefix="/tool_confirmation")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    print("HITL Pattern 1: Tool Confirmation (Frontend Tools)")
    agent_os.serve(app=app, host="127.0.0.1", port=9001)
