"""
AG-UI Showcase
==============

Single server exposing all AG-UI Dojo demo endpoints.
Run this to test AG-UI integration with the Dojo frontend at localhost:3002.

Imports agents from individual files and mounts them at Dojo-compatible paths.
"""

from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

from agentic_chat import agentic_chat_agent
from backend_tool_rendering import backend_tool_agent
from human_in_the_loop import hitl_agent
from tool_based_generative_ui import generative_ui_agent
from shared_state import shared_state_agent
from reasoning_agent import chat_agent as reasoning_agent
from agent_with_media import media_agent

agent_os = AgentOS(
    agents=[
        agentic_chat_agent,
        backend_tool_agent,
        hitl_agent,
        generative_ui_agent,
        shared_state_agent,
        reasoning_agent,
        media_agent,
    ],
    interfaces=[
        AGUI(agent=agentic_chat_agent, prefix="/agentic_chat"),
        AGUI(agent=backend_tool_agent, prefix="/backend_tool_rendering"),
        AGUI(agent=hitl_agent, prefix="/human_in_the_loop"),
        AGUI(agent=generative_ui_agent, prefix="/tool_based_generative_ui"),
        AGUI(agent=shared_state_agent, prefix="/shared_state"),
        AGUI(agent=reasoning_agent, prefix="/agentic_chat_reasoning"),
        AGUI(agent=media_agent, prefix="/agentic_chat_multimodal"),
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    print("AG-UI Showcase Server")
    print("Endpoints:")
    print("  /agentic_chat — Chat, Tools, Streaming")
    print("  /backend_tool_rendering — Agent State, Collaborating")
    print("  /human_in_the_loop — HITL, Interactivity")
    print("  /tool_based_generative_ui — Generative UI (action), Tools")
    print("  /shared_state — Agent State, Collaborating")
    print("  /agentic_chat_reasoning — Chat, Tools, Streaming, Reasoning")
    print("  /agentic_chat_multimodal — Chat, Multimodal, Streaming")
    agent_os.serve(app="showcase:app", reload=True, port=9001)
