from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.vectordb.lancedb import LanceDb, SearchType

agno_assist = Agent(
    name="Agno Assist",
    model=OpenAIChat(id="gpt-4o"),
    description="You help answer questions about the Agno framework.",
    instructions="Search your knowledge before answering the question.",
    knowledge=UrlKnowledge(
        urls=["https://docs.agno.com/llms-full.txt"],
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="agno_assist_knowledge",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    ),
    storage=SqliteStorage(table_name="agno_assist_sessions", db_file="tmp/agents.db"),
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    markdown=True,
)

if __name__ == "__main__":
    agno_assist.knowledge.load()  # Load the knowledge base, comment after first run
    agno_assist.print_response("What is Agno?")
