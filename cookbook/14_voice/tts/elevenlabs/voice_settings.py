"""
ElevenLabs Voice Settings
=========================

Tune ElevenLabs stability, similarity, and speed, and generate audio in smaller chunks.

Talk to it with the voice client in cookbook/05_agent_os/28_voice_pipe/client
(http://localhost:3000/?pipe=voice) or with Agent UI's Voice mode.
Requires OPENAI_API_KEY and ELEVEN_LABS_API_KEY; ELEVEN_LABS_VOICE_ID is optional.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import OpenAIRealtimeSTT
from agno.voice.tts import ElevenLabsTTS
from agno.voice.vad.silero import SileroVAD

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="elevenlabs-tts-voice-settings",
    model=OpenAIResponses(id="gpt-5.6-luna", reasoning_effort="none"),
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
    tts_model=ElevenLabsTTS(
        voice_settings={"stability": 0.4, "similarity_boost": 0.8, "speed": 1.05},
        # Smaller first chunks start speaking sooner.
        chunk_length_schedule=[50, 120, 160, 250],
    ),
)

agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Voice Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="voice_settings:app", reload=True)
