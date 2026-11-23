"""
Send Media to an Agent over AG-UI
=================================

Accept AG-UI image, audio, video, and document content parts and pass them to
a Gemini multimodal agent through one AgentOS interface.

Prerequisites: GOOGLE_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_media.py
Try: Attach an image and ask what it shows through http://localhost:7777/media/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create Multimodal Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-media-db",
    db_file="tmp/agui_media.db",
)

media_agent = Agent(
    id="agui-media-agent",
    name="AG-UI Media Agent",
    model=Gemini(id="gemini-3.5-flash"),
    db=db,
    instructions=(
        "Inspect the user's attached image, audio, video, or document. "
        "Answer only from the supplied content and say when a detail is unclear."
    ),
)

agent_os = AgentOS(
    id="agui-media-os",
    description="A Gemini multimodal agent served through AG-UI.",
    agents=[media_agent],
    interfaces=[AGUI(agent=media_agent, prefix="/media")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Media Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
