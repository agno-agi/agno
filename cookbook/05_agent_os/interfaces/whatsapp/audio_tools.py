"""
Audio Tools Agent
=================

A WhatsApp agent that replies with voice messages using ElevenLabs TTS.
The user sends a text message and the agent generates an audio reply
using the ElevenLabs text_to_speech tool and sends it back as a
WhatsApp voice message.

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  ANTHROPIC_API_KEY
  ELEVEN_LABS_API_KEY
  pip install elevenlabs
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.eleven_labs import ElevenLabsTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent_db = SqliteDb(db_file="tmp/audio_tools.db")

audio_agent = Agent(
    name="Audio Tools Agent",
    model=Gemini("gemini-3-flash-preview"),
    tools=[
        ElevenLabsTools(
            voice_id="21m00Tcm4TlvDq8ikWAM",
            model_id="eleven_multilingual_v2",
        ),
    ],
    db=agent_db,
    instructions=[
        "You are a helpful voice assistant on WhatsApp.",
        "When the user sends a message, use the text_to_speech tool to convert "
        "your reply into audio and send it as a voice message.",
        "Keep your replies concise and conversational since they will be "
        "delivered as voice messages.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    debug_mode=True,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# AgentOS setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[audio_agent],
    interfaces=[Whatsapp(agent=audio_agent, send_user_number_to_context=True)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="audio_tools:app", port=8000)
