"""
HITL Pattern 2: User Input Required
====================================

Minimal backend agent - tools are defined on the frontend.

The frontend registers a tool via `useHumanInTheLoop` that collects user text input.
When the agent calls it, the frontend renders a text input UI.

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
    print("HITL Pattern 2: User Input Required (Frontend Tools)")
    agent_os.serve(app=app, host="127.0.0.1", port=9001)
