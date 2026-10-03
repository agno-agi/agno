"""Talk to an Agno agent that can calculate and search the web.

Run this file to serve the voice pipe at ws://localhost:7777/voice/tools/ws.
Talk to it with the test client in client/ (see README.md), opened at
http://localhost:3000/?pipe=tools. Set OPENAI_API_KEY
and CARTESIA_API_KEY, or set VOICE_TTS_PROVIDER=openai for an OpenAI-only setup.
Web search uses DuckDuckGo through the ddgs package and needs no API key.
Use --check for local tool and route checks without provider calls.

Try saying:
  "What is twelve point five times three?"
  "What is the square root of two hundred and twenty five?"
  "What is the latest news about the James Webb telescope?" Then interrupt
  during the search.

The voice pipeline does not automatically speak filler while a tool is running.
"""

from argparse import ArgumentParser
from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools
from agno.tools.websearch import WebSearchTools
from agno.voice import VoicePipe
from agno.voice.stt.openai import OpenAIRealtimeSTT
from agno.voice.tts.cartesia import CartesiaTTS
from agno.voice.tts.openai import OpenAITTS
from agno.voice.vad.silero import SileroVAD

calculator = CalculatorTools()
web_search = WebSearchTools()

# These are ordinary Agno toolkits; the same agent also serves normal AgentOS runs.
# Runs are stored so voice conversations appear in AgentOS sessions.
db = SqliteDb(
    db_file=str(Path(__file__).resolve().parents[3] / "tmp" / "voice_tools.db")
)

agent = Agent(
    id="voice-tools",
    db=db,
    name="Voice tools assistant",
    model=OpenAIResponses(
        id=getenv("VOICE_AGENT_MODEL", "gpt-5.6-luna"),
        reasoning_effort="none",
        max_output_tokens=300,
    ),
    tools=[calculator, web_search],
    instructions=[
        "Respond in English using short, natural sentences suitable for speech.",
        "Use the calculator tools for arithmetic instead of computing in your head.",
        "Use web search for current events, facts you are unsure of, or anything recent.",
        "Summarize search results in one or two sentences and name the source when useful.",
        "Do not read out URLs, markdown, or long lists.",
        "Do not invent tool results. Ask one short question if information is missing.",
    ],
    markdown=False,
    debug_mode=True,
)

tts_provider = getenv("VOICE_TTS_PROVIDER", "cartesia").lower()
if tts_provider not in {"cartesia", "openai"}:
    raise ValueError("VOICE_TTS_PROVIDER must be 'cartesia' or 'openai'.")

voice = VoicePipe(
    id="tools",
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

agent_os = AgentOS(id="voice-tools-os", agents=[agent], live_sockets=[voice])
app = agent_os.get_app()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check local tools and routes without provider calls",
    )
    args = parser.parse_args()
    if args.check:
        from fastapi.testclient import TestClient

        assert {"add", "multiply", "square_root"} <= set(calculator.functions)
        assert "web_search" in web_search.functions
        assert "37.5" in calculator.multiply(12.5, 3)
        assert "undefined" in calculator.divide(1, 0)
        with TestClient(app):
            assert app.url_path_for("voice_pipe", pipe_id=voice.id) == "/voice/tools/ws"
        print(
            "Calculator, web search registration, and voice routes passed. No provider calls."
        )
    else:
        required_keys = ["OPENAI_API_KEY"] + (
            ["CARTESIA_API_KEY"] if tts_provider == "cartesia" else []
        )
        missing = [name for name in required_keys if not getenv(name)]
        if missing:
            parser.error(
                "Set these environment variables before starting: " + ", ".join(missing)
            )
        print("Voice pipe: ws://localhost:7777/voice/tools/ws")
        print("Test client: http://localhost:3000/?pipe=tools")
        agent_os.serve(app=app, host="localhost", port=7777)
