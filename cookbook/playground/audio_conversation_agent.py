from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.storage.agent.sqlite import SqliteAgentStorage

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
audio_and_text_agent = Agent(
    agent_id="audio-text-agent",
    name="Audio and Text Chat Agent",
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "alloy", "format": "pcm16"},  # Wav not supported for streaming
    ),
    debug_mode=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=PostgresAgentStorage(table_name="agent_sessions", db_url=db_url),
    # storage=SqliteAgentStorage(table_name="audio_agent", db_file="tmp/audio_agent.db"),
)

audio_only_agent = Agent(
    agent_id="audio-only-agent",
    name="Audio Only Chat Agent",
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["audio"],
        audio={"voice": "alloy", "format": "pcm16"},  # Wav not supported for streaming
    ),
    debug_mode=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=PostgresAgentStorage(table_name="agent_sessions", db_url=db_url),
)


app = Playground(agents=[audio_and_text_agent, audio_only_agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("audio_conversation_agent:app", reload=True)
