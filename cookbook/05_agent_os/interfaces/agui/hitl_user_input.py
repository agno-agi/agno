"""
HITL User Input
===============

Minimal backend agent with frontend-defined tools via useHumanInTheLoop.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

user_input_agent = Agent(
    name="user_input",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_hitl_user_input.db"),
    instructions=(
        "You help users with tasks that may need their input. "
        "Use available tools when needed - they are provided by the frontend."
    ),
    markdown=True,
)

agent_os = AgentOS(
    agents=[user_input_agent],
    interfaces=[AGUI(agent=user_input_agent, prefix="/user_input")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_user_input:app", port=9001, reload=True)
