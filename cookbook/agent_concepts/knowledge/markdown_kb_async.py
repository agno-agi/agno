import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.markdown import MarkdownKnowledgeBase
from agno.vectordb.pgvector.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


knowledge_base = MarkdownKnowledgeBase(
    path=Path("README.md"),  # Path to your markdown file(s)
    vector_db=PgVector(
        table_name="markdown_documents",
        db_url=db_url,
    ),
    num_documents=5,  # Number of documents to return on search
)


# Initialize the Assistant with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # This is only needed during the first run
    asyncio.run(knowledge_base.aload(recreate=False))

    asyncio.run(
        agent.aprint_response(
            "What knowledge is available in my knowledge base?",
            markdown=True,
        )
    )
