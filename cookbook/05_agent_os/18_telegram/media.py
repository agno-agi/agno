"""
Send and Receive Media through Telegram
=======================================

Use Gemini to understand photos, voice notes, audio, video, and documents
received from Telegram. Generated images and audio are returned as Agno media
artifacts that the Telegram interface sends back to the chat automatically.

Prerequisites: TELEGRAM_TOKEN, GOOGLE_API_KEY, OPENAI_API_KEY, ELEVEN_LABS_API_KEY, and the `agno[telegram,elevenlabs]` extras
Run: .venvs/demo/bin/python cookbook/05_agent_os/18_telegram/media.py
Try in Telegram: Send a photo and ask for a description, then ask for an image or a short sound effect
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.dalle import DalleTools
from agno.tools.eleven_labs import ElevenLabsTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="telegram-media-db",
    db_file="tmp/telegram_media.db",
)

# ---------------------------------------------------------------------------
# Create Media Agent
# ---------------------------------------------------------------------------

media_agent = Agent(
    id="telegram-media-agent",
    name="Telegram Media Agent",
    model=Gemini(id="gemini-3.5-flash"),
    db=db,
    tools=[
        DalleTools(
            model="dall-e-3",
            size="1024x1024",
            quality="standard",
        ),
        ElevenLabsTools(
            enable_get_voices=False,
            enable_generate_sound_effect=True,
            enable_text_to_speech=True,
        ),
    ],
    instructions=[
        "Help users understand the photos, audio, video, and documents they send.",
        "Use create_image when a user asks you to generate an image.",
        "Use text_to_speech when a user asks you to read text aloud.",
        "Use generate_sound_effect when a user asks for a sound effect.",
        "After using a media tool, briefly describe what you created.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="telegram-media-os",
    description="AgentOS serving a multimodal Telegram assistant.",
    agents=[media_agent],
    interfaces=[
        Telegram(
            agent=media_agent,
            prefix="/telegram",
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
