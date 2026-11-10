"""
Receive and Return WhatsApp Media
=================================

Use one multimodal Agent for inbound WhatsApp images, video, audio, and
documents. Image and video generation tools return media artifacts that the
interface uploads and sends back through the WhatsApp Cloud API.

Prerequisites: GOOGLE_API_KEY, FAL_API_KEY, fal-client, and WhatsApp credentials
Run: .venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/media.py
Try: Send an image for analysis, or ask for a generated image or short video
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.fal import FalTools
from agno.tools.models.gemini import GeminiTools

# ---------------------------------------------------------------------------
# Create the Media WhatsApp AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="whatsapp-media-db",
    db_file="tmp/whatsapp_media.db",
)

media_agent = Agent(
    id="whatsapp-media-agent",
    name="WhatsApp Media Agent",
    model=Gemini(id="gemini-3.5-flash"),
    db=db,
    tools=[
        GeminiTools(
            enable_generate_image=True,
            enable_generate_video=False,
        ),
        FalTools(model="fal-ai/hunyuan-video"),
    ],
    add_history_to_context=True,
    num_history_runs=3,
    instructions=[
        "Analyze images, video, audio, and documents that the user sends.",
        "Use generate_image when the user asks for a new still image.",
        "Use generate_media when the user asks for a short generated video.",
        "Keep accompanying text concise because the result is delivered on WhatsApp.",
    ],
)

agent_os = AgentOS(
    id="whatsapp-media-os",
    description="A multimodal AgentOS that receives and returns WhatsApp media.",
    agents=[media_agent],
    interfaces=[
        Whatsapp(
            agent=media_agent,
            media_timeout=60,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the Media WhatsApp Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
