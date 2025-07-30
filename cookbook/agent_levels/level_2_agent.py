from agno.agent import Agent
from agno.db.sqlite import SqliteStorage
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.anthropic import Claude
from agno.vectordb.lancedb import LanceDb, SearchType

knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        # Use OpenAI for embeddings
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
)

knowledge.add_content(name="Agno Docs", url="https://docs.agno.com/introduction.md")

# Store agent sessions in a SQLite database
storage = SqliteStorage(table_name="agent_sessions", db_file="tmp/agent.db")

agent = Agent(
    name="Agno Assist",
    model=Claude(id="claude-sonnet-4-20250514"),
    instructions=[
        "Search your knowledge before answering the question.",
        "Only include the output in your response. No other text.",
    ],
    knowledge=knowledge,
    storage=storage,
    add_datetime_to_instructions=True,
    # Add the chat history to the messages
    add_history_to_messages=True,
    # Number of history runs
    num_history_runs=3,
    markdown=True,
)

if __name__ == "__main__":
    # Load the knowledge base, comment out after first run
    # Set recreate to True to recreate the knowledge base if needed
    agent.knowledge.load(recreate=False)
    agent.print_response("What is Agno?", stream=True)
