"""Choose the speech-to-text and text-to-speech providers for a voice agent.

AgentOS serves the voice pipe at ws://localhost:7777/voice/providers/pipe. Talk to
it with the test client in client/ (see README.md), opened at
http://localhost:3000/?pipe=providers.

Pick providers with environment variables:

  VOICE_STT_PROVIDER = openai | deepgram | soniox   (default: deepgram)
  VOICE_TTS_PROVIDER = cartesia | elevenlabs | openai   (default: cartesia)

Each provider reads its own key: OPENAI_API_KEY (always needed for the agent),
DEEPGRAM_API_KEY, SONIOX_API_KEY, CARTESIA_API_KEY, or ELEVEN_LABS_API_KEY (with an
optional ELEVEN_LABS_VOICE_ID).

VOICE_STT_LANGUAGE sets Deepgram's language to any code it supports, or "multi"
for speakers who switch languages. Soniox recognizes every language it supports
without hints.

Use --check to validate the configuration without opening provider connections.
"""

from argparse import ArgumentParser
from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import DeepgramSTT, OpenAIRealtimeSTT, SonioxSTT
from agno.voice.tts import CartesiaTTS, ElevenLabsTTS, OpenAITTS
from agno.voice.vad.silero import SileroVAD

STT_KEYS = {
    "openai": "OPENAI_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "soniox": "SONIOX_API_KEY",
}
TTS_KEYS = {
    "cartesia": ["CARTESIA_API_KEY"],
    "elevenlabs": ["ELEVEN_LABS_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}

stt_provider = getenv("VOICE_STT_PROVIDER", "deepgram").lower()
tts_provider = getenv("VOICE_TTS_PROVIDER", "cartesia").lower()
if stt_provider not in STT_KEYS:
    raise ValueError("VOICE_STT_PROVIDER must be openai, deepgram, or soniox.")
if tts_provider not in TTS_KEYS:
    raise ValueError("VOICE_TTS_PROVIDER must be cartesia, elevenlabs, or openai.")

if stt_provider == "deepgram":
    stt_model = DeepgramSTT(
        language=getenv("VOICE_STT_LANGUAGE", "en"), keyterms=["Agno", "AgentOS"]
    )
elif stt_provider == "soniox":
    stt_model = SonioxSTT(terms=["Agno", "AgentOS"])
else:
    stt_model = OpenAIRealtimeSTT(language="en")

if tts_provider == "elevenlabs":
    tts_model = ElevenLabsTTS()
elif tts_provider == "openai":
    tts_model = OpenAITTS(voice="coral", instructions="Speak naturally in English.")
else:
    tts_model = CartesiaTTS(
        voice=getenv("CARTESIA_VOICE_ID", "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"),
        language="en",
    )

# Runs are stored so voice conversations appear in AgentOS sessions.
db = SqliteDb(
    db_file=str(Path(__file__).resolve().parents[3] / "tmp" / "voice_providers.db")
)

agent = Agent(
    id="providers",
    db=db,
    name="Voice providers assistant",
    model=OpenAIResponses(
        id=getenv("VOICE_AGENT_MODEL", "gpt-5.6-luna"),
        reasoning_effort="none",
        max_output_tokens=300,
    ),
    instructions=[
        "You are a helpful voice assistant. Respond in English.",
        "Use short, natural sentences that sound good spoken aloud.",
        "Lead with the answer. Avoid markdown, lists, and lengthy introductions.",
    ],
    markdown=False,
)

voice = VoicePipe(
    id="providers",
    agent=agent,
    vad=SileroVAD(min_silence_duration_ms=320),
    stt_model=stt_model,
    tts_model=tts_model,
)

agent_os = AgentOS(id="voice-providers-os", agents=[agent], live_sockets=[voice])
app = agent_os.get_app()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the configuration without opening provider connections",
    )
    args = parser.parse_args()
    if args.check:
        from fastapi.testclient import TestClient

        with TestClient(app):
            assert (
                app.url_path_for("voice_pipe", pipe_id=voice.id)
                == "/voice/providers/pipe"
            )
        print(
            f"Speech to text: {type(stt_model).__name__}. "
            f"Text to speech: {type(tts_model).__name__}. No provider calls."
        )
    else:
        required = {"OPENAI_API_KEY", STT_KEYS[stt_provider], *TTS_KEYS[tts_provider]}
        missing = sorted(name for name in required if not getenv(name))
        if missing:
            parser.error(
                "Set these environment variables before starting: " + ", ".join(missing)
            )
        print("Voice pipe: ws://localhost:7777/voice/providers/pipe")
        print("Test client: http://localhost:3000/?pipe=providers")
        agent_os.serve(app=app, host="localhost", port=7777)
