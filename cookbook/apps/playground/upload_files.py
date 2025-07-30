from agno.agent import Agent
from agno.db.postgres import PostgresStorage
from agno.knowledge.knowledge import Knowledge
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.playground import Playground
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)

file_agent = Agent(
    name="File Upload Agent",
    agent_id="file-upload-agent",
    role="Answer questions about the uploaded files",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=PostgresStorage(
        table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
    knowledge=knowledge,
    show_tool_calls=True,
    markdown=True,
)


audio_agent = Agent(
    name="Audio Understanding Agent",
    agent_id="audio-understanding-agent",
    role="Answer questions about audio files",
    model=OpenAIChat(id="gpt-4o-audio-preview"),
    storage=PostgresStorage(
        table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
)

video_agent = Agent(
    name="Video Understanding Agent",
    model=Gemini(id="gemini-2.0-flash"),
    agent_id="video-understanding-agent",
    role="Answer questions about video files",
    storage=PostgresStorage(
        table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
)

playground = Playground(
    agents=[file_agent, audio_agent, video_agent],
    name="Upload Files Playground",
    description="Upload files and ask questions about them",
    app_id="upload-files-playground",
)
app = playground.get_app()

if __name__ == "__main__":
    playground.serve(app="upload_files:app", reload=True)
