import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.markdown import MarkdownKnowledgeBase
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "essay-markdown"

vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")

# Initialize the TextKnowledgeBase
knowledge_base = MarkdownKnowledgeBase(
    path=Path("data/mds"),  # Path to your markdown files
    vector_db=vector_db,
    num_documents=5,
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
