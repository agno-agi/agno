"""
Deepgram Multilingual
=====================

Transcribe speakers who switch languages, even mid-sentence, with Deepgram
`nova-3` and `language="multi"`. Deepgram's models and languages overview lists
the languages that multilingual recognition covers.

Talk to it with the voice client in cookbook/05_agent_os/28_voice_pipe/client
(http://localhost:3000/?pipe=voice) or with Agent UI's Voice mode.
Requires OPENAI_API_KEY, DEEPGRAM_API_KEY, and CARTESIA_API_KEY.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.voice import VoicePipe
from agno.voice.stt import DeepgramSTT
from agno.voice.tts import CartesiaTTS
from agno.voice.vad.silero import SileroVAD

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="deepgram-stt-multilingual",
    model=OpenAIResponses(id="gpt-5.6-luna", reasoning_effort="none"),
    db=SqliteDb(db_file="tmp/voice.db"),
    instructions="Reply in the language the user speaks, in short spoken sentences without markdown.",
    markdown=False,
)

# ---------------------------------------------------------------------------
# Create Voice Pipe
# ---------------------------------------------------------------------------
voice = VoicePipe(
    id="voice",
    agent=agent,
    vad=SileroVAD(),
    stt_model=DeepgramSTT(language="multi"),
    tts_model=CartesiaTTS(),
)

agent_os = AgentOS(agents=[agent], live_sockets=[voice])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Voice Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="multilingual:app", reload=True)
