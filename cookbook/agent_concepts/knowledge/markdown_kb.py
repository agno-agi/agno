from pathlib import Path

from agno.agent import Agent
from agno.knowledge.markdown import MarkdownKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


knowledge_base = MarkdownKnowledgeBase(
    path=Path("README.md"),  # Path to your markdown file(s)
    vector_db=PgVector(
        table_name="markdown_documents",
        db_url=db_url,
    ),
    num_documents=5,  # Number of documents to return on search
)

# Load the knowledge base
knowledge_base.load(recreate=False)

# Initialize the Assistant with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

# Ask the agent about the documents in the knowledge base
agent.print_response(
    "What is a good way to get started with Agno?",
    markdown=True,
)
