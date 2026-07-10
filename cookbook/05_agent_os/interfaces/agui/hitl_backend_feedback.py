"""
HITL Backend Feedback
=====================

Minimal backend agent with frontend-defined tools via useHumanInTheLoop.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

backend_feedback_agent = Agent(
    name="backend_feedback",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_hitl_backend_feedback.db"),
    instructions=(
        "You help users make decisions. When a choice would benefit from user input, "
        "use available tools to present options - they are provided by the frontend."
    ),
    markdown=True,
)

agent_os = AgentOS(
    agents=[backend_feedback_agent],
    interfaces=[AGUI(agent=backend_feedback_agent, prefix="/backend_feedback")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_backend_feedback:app", port=9001, reload=True)
