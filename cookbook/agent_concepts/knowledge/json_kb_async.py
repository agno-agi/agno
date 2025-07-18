import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.json import JSONKnowledgeBase
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "json-reader"

vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")

knowledge_base = JSONKnowledgeBase(
    path=Path("tmp/docs"),
    vector_db=vector_db,
    num_documents=5,  # Number of documents to return on search
)

# Initialize the Agent with the knowledge_base
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
            "Ask anything from the json knowledge base", markdown=True
        )
    )
