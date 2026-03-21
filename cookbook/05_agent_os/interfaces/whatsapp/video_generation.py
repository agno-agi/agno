"""
Video Generation Agent
=======================

A WhatsApp agent that generates short videos from text descriptions
using Fal AI's text-to-video models. Demonstrates outbound video
support through the WhatsApp Cloud API.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  FAL_KEY
  pip install fal-client
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.fal import FalTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent_db = SqliteDb(db_file="tmp/video_agent.db")

video_agent = Agent(
    name="Video Generator",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[FalTools(model="fal-ai/hunyuan-video")],
    instructions=[
        "You are a video generation assistant on WhatsApp.",
        "When the user describes a scene, use the generate_media tool to create a short video.",
        "After generating, briefly describe what was created.",
        "Keep messages short and conversational.",
    ],
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    send_media_to_model=False,
)

# ---------------------------------------------------------------------------
# AgentOS setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[video_agent],
    interfaces=[Whatsapp(agent=video_agent)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="video_generation:app", reload=True)
