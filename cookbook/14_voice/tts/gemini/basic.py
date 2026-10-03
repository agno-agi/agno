"""
Gemini TTS
==========

Speak replies with Gemini TTS (`gemini-3.8-flash-lite-tts`, the faster model).
Gemini needs each request's full text, so replies are spoken phrase by phrase
while the agent keeps generating.

Talk to it with the voice client in cookbook/05_agent_os/28_voice_pipe/client
(http://localhost:3000/?pipe=voice) or with Agent UI's Voice mode.
Requires OPENAI_API_KEY and GOOGLE_API_KEY.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import OpenAIRealtimeSTT
from agno.voice.tts import GeminiTTS
from agno.voice.vad.silero import SileroVAD

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="gemini-tts-basic",
    # Flash-Lite keeps voice replies fast; Flash answers if it is unavailable,
    # for example a 503 under high demand.
    model=Gemini(id="gemini-3.5-flash-lite"),
    fallback_models=[Gemini(id="gemini-3.6-flash")],
    db=SqliteDb(db_file="tmp/voice.db"),
    instructions="Respond in short, natural spoken sentences without markdown.",
    markdown=False,
)

# ---------------------------------------------------------------------------
# Create Voice Pipe
# ---------------------------------------------------------------------------
voice = VoicePipe(
    id="voice",
    agent=agent,
    vad=SileroVAD(),
    stt_model=OpenAIRealtimeSTT(),
    tts_model=GeminiTTS(id="gemini-3.8-flash-lite-tts", voice="Kore"),
)

agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Voice Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
