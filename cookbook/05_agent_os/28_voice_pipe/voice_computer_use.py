"""Talk to the computer use agent: ask out loud and it drives your screen.

Reuses the agent from cookbook/91_tools/computer_use/computer_use_agent.py and
serves it at ws://localhost:7777/voice/computer/ws. Talk to it with the test
client in client/ (see README.md), opened at http://localhost:3000/?pipe=computer.
Listens with Soniox. Requires pyautogui, OPENAI_API_KEY, SONIOX_API_KEY, and
CARTESIA_API_KEY, or set VOICE_TTS_PROVIDER=openai to speak with OpenAI instead
of Cartesia.
Use --check for a route check without provider calls.

Try saying:
  "Minimize this window, open Chrome, and go to agno dot com."
  "Open Notepad and type hello from Agno."

This agent really clicks and types on your machine. Watch it while it runs, and
move the mouse into a screen corner to abort. Speaking while it works interrupts
the reply and cancels the task, so stay quiet until it finishes. The window it
minimizes first is usually this browser tab's window; voice keeps working while
it is minimized.
"""

import sys
from argparse import ArgumentParser
from os import getenv
from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt.soniox import SonioxSTT
from agno.voice.tts.cartesia import CartesiaTTS
from agno.voice.tts.openai import OpenAITTS
from agno.voice.vad.silero import SileroVAD

# The cookbook folders are not Python packages, so import the example by path.
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root / "cookbook" / "91_tools" / "computer_use"))
from computer_use_agent import agent  # noqa: E402

# Speech should not read markdown symbols aloud.
agent.markdown = False

tts_provider = getenv("VOICE_TTS_PROVIDER", "cartesia").lower()
if tts_provider not in {"cartesia", "openai"}:
    raise ValueError("VOICE_TTS_PROVIDER must be 'cartesia' or 'openai'.")

voice = VoicePipe(
    id="computer",
    agent=agent,
    vad=SileroVAD(min_silence_duration_ms=320),
    # Soniox takes language codes, not regional variants such as en-IN.
    stt_model=SonioxSTT(language_hints=["en"]),
    tts_model=(
        CartesiaTTS(
            voice="7ea5e9c2-b719-4dc3-b870-5ba5f14d31d8",
            language="en",
        )
        if tts_provider == "cartesia"
        else OpenAITTS(
            voice="coral", instructions="Speak clearly and naturally in English."
        )
    ),
    # Multi-step screen tasks take longer than the 60 second default.
    response_timeout=300,
)

agent_os = AgentOS(
    id="voice-computer-use-os",
    agents=[agent],
    live_sockets=[voice],
    # Agents without their own db get this one, so voice runs are stored.
    db=SqliteDb(db_file=str(repo_root / "tmp" / "voice_computer_use.db")),
)
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

        assert {"take_screenshot", "click", "type_text"} <= set(
            name for toolkit in agent.tools for name in toolkit.functions
        )
        with TestClient(app):
            assert (
                app.url_path_for("voice_pipe", pipe_id=voice.id) == "/voice/computer/ws"
            )
        print("Computer use agent and voice route passed. No provider calls.")
    else:
        required_keys = ["OPENAI_API_KEY", "SONIOX_API_KEY"] + (
            ["CARTESIA_API_KEY"] if tts_provider == "cartesia" else []
        )
        missing = [name for name in required_keys if not getenv(name)]
        if missing:
            parser.error(
                "Set these environment variables before starting: " + ", ".join(missing)
            )
        print("Voice pipe: ws://localhost:7777/voice/computer/ws")
        print("Test client: http://localhost:3000/?pipe=computer")
        agent_os.serve(app=app, host="localhost", port=7777)
