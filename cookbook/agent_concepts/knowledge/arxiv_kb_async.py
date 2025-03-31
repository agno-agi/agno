import asyncio

from agno.agent import Agent
from agno.knowledge.arxiv import ArxivKnowledgeBase
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "arxive-reader"

vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")

# Create a knowledge base with the ArXiv documents
knowledge_base = ArxivKnowledgeBase(
    queries=["Generative AI", "Machine Learning"], vector_db=vector_db
)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=False))

    # Create and use the agent
    asyncio.run(
        agent.aprint_response(
            "Ask me about generative ai from the knowledge base", markdown=True
        )
    )
