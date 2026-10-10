"""
OpenAI TTS
==========

Speak replies with OpenAI text to speech, steered by speaking instructions.

Talk to it with the voice client in cookbook/05_agent_os/28_voice_pipe/client
(http://localhost:3000/?pipe=voice) or with Agent UI's Voice mode.
Requires OPENAI_API_KEY.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import OpenAIRealtimeSTT
from agno.voice.tts import OpenAITTS
from agno.voice.vad.silero import SileroVAD

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="openai-tts-basic",
    model=OpenAIResponses(id="gpt-5.6-luna", reasoning_effort="none"),
    db=SqliteDb(db_file="tmp/voice.db"),
    instructions="Respond in short, natural spoken sentences without markdown.",
    markdown=False,
)

# ---------------------------------------------------------------------------
# Create Voice Pipe
# ---------------------------------------------------------------------------
# OpenAI TTS buffers short phrases; it does not accept a live text stream.
voice = VoicePipe(
    id="voice",
    agent=agent,
    vad=SileroVAD(),
    stt_model=OpenAIRealtimeSTT(),
    tts_model=OpenAITTS(
        voice="coral", instructions="Speak warmly and at a relaxed pace."
    ),
)

agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Voice Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
