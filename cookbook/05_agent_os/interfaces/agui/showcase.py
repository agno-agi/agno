"""
AG-UI Showcase
==============

Demonstrates all AG-UI demos on a single server.
"""

from agent_with_media import media_agent
from agentic_chat import agentic_chat_agent
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from backend_tool_rendering import backend_tool_agent
from hitl_backend_feedback import backend_feedback_agent
from hitl_tool_confirmation import confirmation_agent
from hitl_user_input import user_input_agent
from human_in_the_loop import hitl_agent
from reasoning_agent import chat_agent as reasoning_agent
from shared_state import shared_state_agent
from team_human_in_the_loop import support_team
from tool_based_generative_ui import generative_ui_agent

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[
        agentic_chat_agent,
        backend_tool_agent,
        hitl_agent,
        generative_ui_agent,
        shared_state_agent,
        reasoning_agent,
        media_agent,
        confirmation_agent,
        user_input_agent,
        backend_feedback_agent,
    ],
    teams=[support_team],
    interfaces=[
        AGUI(agent=agentic_chat_agent, prefix="/agentic_chat"),
        AGUI(agent=backend_tool_agent, prefix="/backend_tool_rendering"),
        AGUI(agent=hitl_agent, prefix="/human_in_the_loop"),
        AGUI(agent=generative_ui_agent, prefix="/tool_based_generative_ui"),
        AGUI(agent=shared_state_agent, prefix="/shared_state"),
        AGUI(agent=reasoning_agent, prefix="/agentic_chat_reasoning"),
        AGUI(agent=media_agent, prefix="/agentic_chat_multimodal"),
        AGUI(agent=confirmation_agent, prefix="/tool_confirmation"),
        AGUI(agent=user_input_agent, prefix="/user_input"),
        AGUI(agent=backend_feedback_agent, prefix="/backend_feedback"),
        AGUI(team=support_team, prefix="/team_human_in_the_loop"),
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="showcase:app", reload=True, port=9001)
