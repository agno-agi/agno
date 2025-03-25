from agno.agent import Agent
from agno.knowledge.combined import CombinedKnowledgeBase
from agno.knowledge.csv import CSVKnowledgeBase
from agno.knowledge.docx import DocxKnowledgeBase
from agno.knowledge.json import JSONKnowledgeBase
from agno.knowledge.pdf import PDFKnowledgeBase
from agno.knowledge.text import TextKnowledgeBase
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.playground.playground import Playground
from agno.playground.serve import serve_playground_app
from agno.storage.postgres import PostgresStorage
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = CombinedKnowledgeBase(
    sources=[
        PDFKnowledgeBase(
            vector_db=PgVector(table_name="recipes_pdf", db_url=db_url), path=""
        ),
        CSVKnowledgeBase(
            vector_db=PgVector(table_name="recipes_csv", db_url=db_url), path=""
        ),
        DocxKnowledgeBase(
            vector_db=PgVector(table_name="recipes_docx", db_url=db_url), path=""
        ),
        JSONKnowledgeBase(
            vector_db=PgVector(table_name="recipes_json", db_url=db_url), path=""
        ),
        TextKnowledgeBase(
            vector_db=PgVector(table_name="recipes_text", db_url=db_url), path=""
        ),
    ],
    vector_db=PgVector(table_name="recipes_combined", db_url=db_url),
)

file_agent = Agent(
    name="File Upload Agent",
    agent_id="file-upload-agent",
    role="Answer questions about the uploaded files",
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=PostgresStorage(
        table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
    knowledge=knowledge_base,
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

app = Playground(agents=[file_agent, audio_agent, video_agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("upload_files:app", reload=True)
