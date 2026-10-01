"""Talk to an Agno agent that answers questions from the Agno documentation.

Run this file to serve the voice pipe at ws://localhost:7777/voice/knowledge/pipe.
Talk to it with the test client in client/ (see README.md), opened at
http://localhost:3000/?pipe=knowledge.
Requires lancedb, OPENAI_API_KEY, and CARTESIA_API_KEY. The first run embeds
https://docs.agno.com/llms.txt into a local LanceDB table; later runs reuse it.
VOICE_TTS_PROVIDER=openai selects the OpenAI-only speech alternative.

Try: "What is AgentOS?"
Try: "How do I give an agent memory?"
Try: "What is the difference between a team and a workflow?"
Use --check for an offline configuration check.
"""

from argparse import ArgumentParser
from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.vectordb.lancedb import LanceDb, SearchType
from agno.voice import VoicePipe
from agno.voice.stt.openai import OpenAIRealtimeSTT
from agno.voice.tts.cartesia import CartesiaTTS
from agno.voice.tts.openai import OpenAITTS
from agno.voice.vad.silero import SileroVAD

data_dir = Path(__file__).resolve().parents[3] / "tmp" / "voice_knowledge"

agno_docs = Knowledge(
    vector_db=LanceDb(
        uri=str(data_dir / "lancedb"),
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Runs are stored so voice conversations appear in AgentOS sessions.
db = SqliteDb(db_file=str(data_dir / "voice_knowledge.db"))

agent = Agent(
    id="knowledge",
    db=db,
    name="Agno docs assistant",
    model=OpenAIResponses(
        id=getenv("VOICE_AGENT_MODEL", "gpt-5.6-luna"),
        reasoning_effort="none",
        max_output_tokens=300,
    ),
    knowledge=agno_docs,
    search_knowledge=True,
    instructions=[
        "You answer questions about the Agno framework using its documentation.",
        "Search your knowledge before answering questions about Agno.",
        "If the documentation does not contain the answer, say so. Do not invent APIs.",
        "Respond in English in one to three short sentences, without markdown.",
        "Describe code in words instead of reading it out symbol by symbol.",
    ],
    markdown=False,
    debug_mode=True,
)

tts_provider = getenv("VOICE_TTS_PROVIDER", "cartesia").lower()
if tts_provider not in {"cartesia", "openai"}:
    raise ValueError("VOICE_TTS_PROVIDER must be 'cartesia' or 'openai'.")

voice = VoicePipe(
    id="knowledge",
    agent=agent,
    vad=SileroVAD(min_silence_duration_ms=320),
    stt_model=OpenAIRealtimeSTT(language="en"),
    tts_model=(
        CartesiaTTS(
            voice=getenv("CARTESIA_VOICE_ID", "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"),
            language="en",
        )
        if tts_provider == "cartesia"
        else OpenAITTS(voice="coral", instructions="Speak naturally in English.")
    ),
)
agent_os = AgentOS(id="voice-knowledge-os", agents=[agent], live_sockets=[voice])
app = agent_os.get_app()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check locally without API calls"
    )
    args = parser.parse_args()
    if args.check:
        from fastapi.testclient import TestClient

        with TestClient(app):
            assert (
                app.url_path_for("voice_pipe", pipe_id=voice.id)
                == "/voice/knowledge/pipe"
            )
        print("Knowledge configuration and voice route checked. No API calls made.")
    else:
        required_keys = ["OPENAI_API_KEY"] + (
            ["CARTESIA_API_KEY"] if tts_provider == "cartesia" else []
        )
        missing = [name for name in required_keys if not getenv(name)]
        if missing:
            parser.error("Set these environment variables: " + ", ".join(missing))
        print("Loading the Agno docs. The first run embeds them and takes a while...")
        agno_docs.insert(
            name="Agno Docs",
            url="https://docs.agno.com/llms.txt",
            skip_if_exists=True,
        )
        print("Voice pipe: ws://localhost:7777/voice/knowledge/pipe")
        print("Test client: http://localhost:3000/?pipe=knowledge")
        agent_os.serve(app=app, host="localhost", port=7777)
