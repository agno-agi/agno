"""
HITL Pattern 3: Multiple Choice Feedback
==========================================

Minimal backend agent - tools are defined on the frontend.

The frontend registers a tool via `useHumanInTheLoop` that presents multiple choice.
When the agent calls it, the frontend renders the options UI.

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
    print("HITL Pattern 3: Multiple Choice Feedback (Frontend Tools)")
    agent_os.serve(app=app, host="127.0.0.1", port=9001)
