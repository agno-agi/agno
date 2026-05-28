"""
AgentOS Docling Markdown Analyst
========================

Demonstrates AgentOS markdown analyst using Docling reader.
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docling_reader import DoclingReader
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

docling_knowledge = Knowledge(
    name="Docling Markdowns",
    contents_db=db,  # Required for UI to show knowledge
    vector_db=PgVector(
        db_url=db_url,
        table_name="agentos_docling_knowledge",
    ),
)

docling_agent = Agent(
    name="Docling Markdown Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,  # For session storage
    knowledge=docling_knowledge,
    search_knowledge=True,
    markdown=True,
    instructions=[
        "You are a markdown analyst assistant with access to markdown data.",
        "Search the knowledge base to answer questions about the markdowns.",
        "Provide specific details and quotes when available.",
    ],
)

# Create AgentOS app
agent_os = AgentOS(
    description="Docling Knowledge API - Query markdowns via REST",
    agents=[docling_agent],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    repo_root = Path(__file__).parent.parent.parent.parent
    sample_file = repo_root / "cookbook/07_knowledge/testing_resources/coffee.md"

    if sample_file.exists():
        print("Loading coffee guide with Docling...")
        docling_knowledge.insert(
            path=str(sample_file),
            reader=DoclingReader(),
            skip_if_exists=True,
        )

    print("\nStarting AgentOS server...")
    print("Test at: http://localhost:7777/")
    print("\nExample queries:")
    print("  - What is the difference between a cappuccino and a latte?")
    print("  - How do you make an espresso?")
    print("  - What are the different types of brewed coffee?")

    agent_os.serve(app="agentos_docling_markdown_analyst:app", reload=True)
