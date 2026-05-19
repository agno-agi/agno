"""
Agent With Media
================

Demonstrates an AG-UI agent that accepts multimodal user input.

The agent uses Google Gemini, which can analyze images, audio, video, and
documents. When a user attaches a file in an AG-UI frontend, the AG-UI
interface forwards it to the agent as the matching media type and the agent
answers questions about it.

Setup: Set the GOOGLE_API_KEY environment variable.
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
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9001/config

    Use Port 9001 to configure the Dojo endpoint, then attach an image,
    audio, video, or document in the frontend.
    """
    agent_os.serve(app="agent_with_media:app", port=9001, reload=True)
