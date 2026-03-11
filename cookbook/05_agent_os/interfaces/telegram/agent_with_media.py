"""
Telegram Media Agent
====================

Multimedia Telegram bot that can generate images with DALL-E, produce
speech and sound effects with ElevenLabs, and analyze images, audio,
and video that users send.

Key concepts:
  - ``DalleTools`` for image generation from text prompts.
  - ``ElevenLabsTools`` for text-to-speech and sound effect generation.
  - Telegram interface automatically sends generated media files back to chat.

Setup: Set TELEGRAM_TOKEN env var from @BotFather.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.dalle import DalleTools
from agno.tools.eleven_labs import ElevenLabsTools

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(
    session_table="telegram_media_sessions", db_file="tmp/telegram_media.db"
)

media_agent = Agent(
    name="Media Agent",
    model=Gemini(id="gemini-2.5-pro"),
    db=agent_db,
    tools=[
        DalleTools(model="dall-e-3", size="1024x1024", quality="standard"),
        ElevenLabsTools(
            enable_text_to_speech=True,
            enable_generate_sound_effect=True,
            enable_get_voices=False,
        ),
    ],
    instructions=[
        "You are a helpful multimedia assistant on Telegram.",
        "When asked to generate, create, or draw an image, use the DALL-E tool.",
        "When asked to speak, read aloud, or convert text to speech, use the ElevenLabs text_to_speech tool.",
        "When asked for a sound effect, use the ElevenLabs generate_sound_effect tool.",
        "Keep text responses concise and friendly.",
        "You can also analyze images, audio, and video that users send you.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[media_agent],
    interfaces=[
        Telegram(
            agent=media_agent,
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="agent_with_media:app", reload=True)
