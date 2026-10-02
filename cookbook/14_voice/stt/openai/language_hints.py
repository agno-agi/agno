"""
OpenAI Realtime STT Language Hints
==================================

Tell OpenAI which languages to expect and boost recognition of keywords.

Set VOICE_LANGUAGES to a comma-separated list of the language codes your users
speak; OpenAI's speech-to-text guide lists the supported languages.

Talk to it with the voice client in cookbook/05_agent_os/28_voice_pipe/client
(http://localhost:3000/?pipe=voice) or with Agent UI's Voice mode.
Requires OPENAI_API_KEY and CARTESIA_API_KEY.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import OpenAIRealtimeSTT
from agno.voice.tts import CartesiaTTS
from agno.voice.vad.silero import SileroVAD

languages = [
    code.strip() for code in getenv("VOICE_LANGUAGES", "en").split(",") if code.strip()
]

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="openai-stt-language-hints",
    model=OpenAIResponses(id="gpt-5.6-luna", reasoning_effort="none"),
    db=SqliteDb(db_file="tmp/voice.db"),
    instructions="Reply in the language the user speaks, in short spoken sentences without markdown.",
    markdown=False,
)

# ---------------------------------------------------------------------------
# Create Voice Pipe
# ---------------------------------------------------------------------------
# Multiple language hints need gpt-live-transcribe or gpt-transcribe.
voice = VoicePipe(
    id="voice",
    agent=agent,
    vad=SileroVAD(),
    stt_model=OpenAIRealtimeSTT(languages=languages, keywords=["Agno", "AgentOS"]),
    tts_model=CartesiaTTS(),
)

agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Voice Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="language_hints:app", reload=True)
