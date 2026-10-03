"""
Soniox Language Hints
=====================

Bias Soniox toward the languages your users speak. Without hints, Soniox
recognizes every language it supports and handles switching mid-sentence; hints
only make the expected languages more likely.

Set VOICE_LANGUAGES to a comma-separated list of language codes from Soniox's
supported languages page.

Talk to it with the voice client in cookbook/05_agent_os/28_voice_pipe/client
(http://localhost:3000/?pipe=voice) or with Agent UI's Voice mode.
Requires OPENAI_API_KEY, SONIOX_API_KEY, and CARTESIA_API_KEY.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import SonioxSTT
from agno.voice.tts import CartesiaTTS
from agno.voice.vad.silero import SileroVAD

languages = [
    code.strip() for code in getenv("VOICE_LANGUAGES", "en").split(",") if code.strip()
]

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="soniox-stt-language-hints",
    model=OpenAIResponses(id="gpt-5.6-luna", reasoning_effort="none"),
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
    stt_model=SonioxSTT(language_hints=languages),
    tts_model=CartesiaTTS(),
)

agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Voice Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="language_hints:app", reload=True)
