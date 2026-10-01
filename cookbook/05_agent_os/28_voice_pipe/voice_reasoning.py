"""Talk to an Agno agent backed by a model that reasons natively before it answers.

Run this file to serve the voice pipe at ws://localhost:7777/voice/reasoning/pipe.
Talk to it with the test client in client/ (see README.md), opened at
http://localhost:3000/?pipe=reasoning. Set OPENAI_API_KEY and CARTESIA_API_KEY,
or set VOICE_TTS_PROVIDER=openai for an OpenAI-only setup.
Use --check for a route check without provider calls.

The model's own reasoning runs before the reply. VOICE_REASONING_EFFORT sets its
effort (default "low"; "medium" or "high" think longer). Reasoning summaries are
stored with each run for AgentOS, but only the final answer is spoken. Reasoning
adds time before the first word; higher effort adds more.

Try saying:
  "A bat and a ball cost one dollar ten. The bat costs a dollar more than the
  ball. How much is the ball?"
  "If I leave at four forty and the drive takes an hour and thirty five minutes,
  with a fifteen minute stop, when do I arrive?"
  "Should I take a job with a longer commute but twenty percent more pay?"
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

# Runs are stored so voice conversations appear in AgentOS sessions.
db = SqliteDb(
    db_file=str(Path(__file__).resolve().parents[3] / "tmp" / "voice_reasoning.db")
)

agent = Agent(
    id="voice-reasoning",
    db=db,
    name="Voice reasoning assistant",
    model=OpenAIResponses(
        id=getenv("VOICE_AGENT_MODEL", "gpt-5.6-luna"),
        reasoning_effort=getenv("VOICE_REASONING_EFFORT", "low"),
        # Store a summary of the model's reasoning on each run for observability.
        reasoning_summary="auto",
        # Reasoning tokens count toward this limit, so allow more room than the
        # other examples while the instructions keep the spoken answer short.
        max_output_tokens=4000,
    ),
    instructions=[
        "Respond in English using short, natural sentences suitable for speech.",
        "Speak only the conclusion and the one or two reasons that matter most.",
        "Do not read out your reasoning steps, lists, or markdown.",
        "If the question is ambiguous, ask one short clarifying question instead.",
    ],
    markdown=False,
    debug_mode=True,
)

tts_provider = getenv("VOICE_TTS_PROVIDER", "cartesia").lower()
if tts_provider not in {"cartesia", "openai"}:
    raise ValueError("VOICE_TTS_PROVIDER must be 'cartesia' or 'openai'.")

voice = VoicePipe(
    id="reasoning",
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

agent_os = AgentOS(id="voice-reasoning-os", agents=[agent], live_sockets=[voice])
app = agent_os.get_app()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check the voice route without provider calls",
    )
    args = parser.parse_args()
    if args.check:
        from fastapi.testclient import TestClient

        with TestClient(app):
            assert (
                app.url_path_for("voice_pipe", pipe_id=voice.id)
                == "/voice/reasoning/pipe"
            )
        print("Reasoning agent and voice route passed. No provider calls.")
    else:
        required_keys = ["OPENAI_API_KEY"] + (
            ["CARTESIA_API_KEY"] if tts_provider == "cartesia" else []
        )
        missing = [name for name in required_keys if not getenv(name)]
        if missing:
            parser.error(
                "Set these environment variables before starting: " + ", ".join(missing)
            )
        print("Voice pipe: ws://localhost:7777/voice/reasoning/pipe")
        print("Test client: http://localhost:3000/?pipe=reasoning")
        agent_os.serve(app=app, host="localhost", port=7777)
