import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_assist_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

asyncio.run(
    knowledge.add_content_async(
        name="Agno Docs", url="https://docs.agno.com/llms-full.txt"
    )
)

agno_assist = Agent(
    name="Agno Assist",
    model=OpenAIChat(id="gpt-4o"),
    description="You help answer questions about the Agno framework.",
    instructions="Search your knowledge before answering the question.",
    knowledge=knowledge,
    db=SqliteDb(session_table="agno_assist_sessions", db_file="tmp/agents.db"),
    add_history_to_context=True,
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agno_assist.print_response("What is Agno?")
