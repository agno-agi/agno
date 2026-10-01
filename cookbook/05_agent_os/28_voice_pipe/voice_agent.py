"""Give an existing Agno agent a streaming voice interface through AgentOS.

Set OPENAI_API_KEY and CARTESIA_API_KEY, then run this file. AgentOS serves the
voice pipe at ws://localhost:7777/voice/assistant/pipe. Talk to it with the test
client in client/ (see README.md), opened at http://localhost:3000/?pipe=assistant.
Use --check to validate routes without opening speech-provider connections or
downloading a VAD model.
Set VOICE_TTS_PROVIDER=openai for an OpenAI-only setup without a Cartesia key.
"""

from argparse import ArgumentParser
from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt.openai import OpenAIRealtimeSTT
from agno.voice.tts.cartesia import CartesiaTTS
from agno.voice.tts.openai import OpenAITTS
from agno.voice.vad.silero import SileroVAD

# Reuse this agent for both ordinary AgentOS requests and voice conversations.
# Runs are stored so voice conversations appear in AgentOS sessions.
db = SqliteDb(
    db_file=str(Path(__file__).resolve().parents[3] / "tmp" / "voice_agent.db")
)

agent = Agent(
    id="assistant",
    db=db,
    name="Voice assistant",
    model=OpenAIResponses(
        id=getenv("VOICE_AGENT_MODEL", "gpt-5.6-luna"),
        reasoning_effort="none",
        max_output_tokens=300,
    ),
    instructions=[
        "You are a helpful voice assistant. Respond in English.",
        "Use short, natural sentences that sound good spoken aloud.",
        "Lead with the answer. Avoid markdown, lists, and lengthy introductions.",
        "Ask one short follow-up question when you need more information.",
    ],
    markdown=False,
    debug_mode=True,
)

tts_provider = getenv("VOICE_TTS_PROVIDER", "cartesia").lower()
if tts_provider not in {"cartesia", "openai"}:
    raise ValueError("VOICE_TTS_PROVIDER must be 'cartesia' or 'openai'.")

voice = VoicePipe(
    id="assistant",
    agent=agent,
    vad=SileroVAD(min_silence_duration_ms=320),
    stt_model=OpenAIRealtimeSTT(language="en"),
    tts_model=(
        CartesiaTTS(
            voice=getenv("CARTESIA_VOICE_ID", "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"),
            language="en",
        )
        if tts_provider == "cartesia"
        else OpenAITTS(
            voice="coral", instructions="Speak clearly and naturally in English."
        )
    ),
)

agent_os = AgentOS(
    id="voice-agent-os",
    agents=[agent],
    live_sockets=[voice],
)
app = agent_os.get_app()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate route registration without making API calls",
    )
    args = parser.parse_args()
    if args.check:
        from fastapi.testclient import TestClient

        with TestClient(app):
            assert (
                app.url_path_for("voice_pipe", pipe_id=voice.id)
                == "/voice/assistant/pipe"
            )
        print("Voice routes are registered. No provider connections were opened.")
    else:
        required_keys = ["OPENAI_API_KEY"] + (
            ["CARTESIA_API_KEY"] if tts_provider == "cartesia" else []
        )
        missing = [name for name in required_keys if not getenv(name)]
        if missing:
            parser.error(
                "Set these environment variables before starting: " + ", ".join(missing)
            )
        print("Voice pipe: ws://localhost:7777/voice/assistant/pipe")
        print("Test client: http://localhost:3000/?pipe=assistant")
        agent_os.serve(app=app, host="localhost", port=7777)
