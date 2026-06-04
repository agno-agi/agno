"""
Agent With Media
================
AG-UI agent that accepts multimodal input (images, audio, video, documents).

Uses Google Gemini to analyze attached files. Set GOOGLE_API_KEY env var.
"""

from agno.agent.agent import Agent
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

media_agent = Agent(
    name="Media Agent",
    model=Gemini(id="gemini-flash-latest"),
    instructions="Analyze any image, audio, video, or document the user sends and answer their question about it.",
    add_datetime_to_context=True,
    markdown=True,
)

# Setup your AgentOS app
agent_os = AgentOS(
    agents=[media_agent],
    interfaces=[AGUI(agent=media_agent)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="agent_with_media:app", port=9001, reload=True)
