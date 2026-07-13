"""
HITL Tool Confirmation
======================

Minimal backend agent with frontend-defined tools via useHumanInTheLoop.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

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
    agent_os.serve(app="hitl_tool_confirmation:app", port=9001, reload=True)
