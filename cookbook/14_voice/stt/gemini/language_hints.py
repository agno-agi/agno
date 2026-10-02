"""
Gemini Live STT Language Hints
==============================

Bias Gemini Live transcription toward expected languages and add custom vocabulary.

Set VOICE_LANGUAGES to a comma-separated list of BCP-47 codes from Google's
supported languages list, such as "es-ES,fr-FR". Leave it unset for automatic
language detection.

Talk to it with the voice client in cookbook/05_agent_os/28_voice_pipe/client
(http://localhost:3000/?pipe=voice) or with Agent UI's Voice mode.
Requires GOOGLE_API_KEY and CARTESIA_API_KEY.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import GeminiLiveSTT
from agno.voice.tts import CartesiaTTS
from agno.voice.vad.silero import SileroVAD

languages = [
    code.strip() for code in getenv("VOICE_LANGUAGES", "").split(",") if code.strip()
]

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="gemini-stt-language-hints",
    # Flash-Lite keeps voice replies fast; Flash answers if it is unavailable,
    # for example a 503 under high demand.
    model=Gemini(id="gemini-3.5-flash-lite"),
    fallback_models=[Gemini(id="gemini-3.6-flash")],
    db=SqliteDb(db_file="tmp/voice.db"),
    instructions="Reply in the language the user speaks, in short spoken sentences without markdown.",
    markdown=False,
)

# ---------------------------------------------------------------------------
# Create Voice Pipe
# ---------------------------------------------------------------------------
voice = VoicePipe(
    id="voice",
    agent=agent,
    vad=SileroVAD(),
    stt_model=GeminiLiveSTT(
        languages=languages, vocabulary=["Agno", "AgentOS", "VoicePipe"]
    ),
    tts_model=CartesiaTTS(),
)

agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Voice Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="language_hints:app", reload=True)
