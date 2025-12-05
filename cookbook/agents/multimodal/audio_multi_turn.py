from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file
from rich.pretty import pprint

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "wav"},
    ),
    add_history_to_context=True,
    db=SqliteDb(
        session_table="audio_multi_turn_sessions", db_file="tmp/audio_multi_turn.db"
    ),
)

run_response = agent.run("Is a golden retriever a good family dog?")
pprint(run_response.content)
if run_response.response_audio is not None:
    write_audio_to_file(
        audio=run_response.response_audio.content, filename="tmp/answer_1.wav"
    )

run_response = agent.run("What breed are we talking about?")
pprint(run_response.content)
if run_response.response_audio is not None:
    write_audio_to_file(
        audio=run_response.response_audio.content, filename="tmp/answer_2.wav"
    )
