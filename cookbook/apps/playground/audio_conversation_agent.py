from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage

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
    storage=SqliteStorage(
        table_name="audio_agent", db_file="tmp/audio_agent.db", auto_upgrade_schema=True
    ),
)

playground = Playground(
    agents=[audio_and_text_agent],
    name="Audio Conversation Agent",
    description="A playground for audio conversation agent",
    app_id="audio-conversation-agent",
)
app = playground.get_app()

if __name__ == "__main__":
    playground.serve(app="audio_conversation_agent:app", reload=True)
